#!/usr/bin/env python3
"""Local browser editor for input files and Makefile targets."""
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
EDITABLE_FILES = ("format.tex", "header.yaml", "geometry.yaml", "resume.json")
MAKE_TARGETS = ("build", "user")

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resume Workshop</title>
<style>
:root { color-scheme: light; --ink:#17212b; --muted:#617080; --line:#d5dde4; --paper:#fff; --wash:#eef3f1; --accent:#be4d32; --accent-dark:#8d3425; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:linear-gradient(135deg,#eef3f1 0%,#f8f5ef 55%,#e8eef3 100%); font:15px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
header { padding:28px 5vw 20px; display:flex; justify-content:space-between; align-items:end; gap:20px; }
h1 { margin:0; font:700 clamp(1.8rem,4vw,3.2rem)/1 Georgia,serif; letter-spacing:0; }
header p { max-width:48rem; margin:8px 0 0; color:var(--muted); font-family:ui-sans-serif,system-ui,sans-serif; }
main { width:min(1400px,90vw); margin:0 auto 40px; display:grid; grid-template-columns:minmax(0,1.5fr) minmax(280px,.7fr); gap:18px; }
.panel { background:rgba(255,255,255,.88); border:1px solid var(--line); box-shadow:0 12px 30px rgba(23,33,43,.08); }
.tabs { display:flex; flex-wrap:wrap; border-bottom:1px solid var(--line); background:#f7faf9; }
.tab { border:0; border-right:1px solid var(--line); padding:13px 15px; background:transparent; color:var(--muted); cursor:pointer; font:inherit; }
.tab.active { color:var(--ink); background:var(--paper); box-shadow:inset 0 -3px var(--accent); }
.editor { width:100%; min-height:650px; display:block; resize:vertical; border:0; padding:22px; color:#24313c; background:var(--paper); outline:none; font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; tab-size:2; }
.editor-shell { position:relative; }
.editor-shell .highlight { position:absolute; inset:0; margin:0; padding:22px; overflow:auto; pointer-events:none; white-space:pre-wrap; word-wrap:break-word; color:#24313c; background:var(--paper); font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; tab-size:2; }
.editor-shell.nowrap .highlight, .editor-shell.nowrap .editor { white-space:pre; }
.highlight .cmd { color:var(--accent-dark); font-weight:600; }
.highlight .key { color:#1f6f78; font-weight:600; }
.editor-shell .editor { position:relative; background:transparent; color:transparent; caret-color:#24313c; white-space:pre-wrap; word-wrap:break-word; }
.actions { padding:15px; display:flex; flex-wrap:wrap; gap:8px; border-top:1px solid var(--line); }
button { border:1px solid #bdc8d0; background:#fff; color:var(--ink); padding:9px 12px; cursor:pointer; font:inherit; }
button:hover { border-color:var(--accent); color:var(--accent-dark); } button.primary { background:var(--accent); border-color:var(--accent); color:white; } button.primary:hover { background:var(--accent-dark); color:white; }
.side { padding:18px; } h2 { margin:0 0 14px; font:700 1.2rem Georgia,serif; } .target-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.status { margin-top:18px; padding:12px; min-height:180px; white-space:pre-wrap; overflow:auto; background:#17212b; color:#dce9e4; font-size:12px; }
.pdf { margin-top:18px; width:100%; min-height:500px; border:1px solid var(--line); background:#8b969d; }
@media (max-width:850px) { header { display:block; } main { grid-template-columns:1fr; } .editor { min-height:500px; } .pdf { min-height:650px; } }
</style>
</head>
<body>
<header><div><h1>Resume Workshop</h1><p>Edit source files, run the pipeline, and inspect the generated PDF from one local page.</p></div><button id="openPdf">Open PDF</button></header>
<main>
<section class="panel"><nav class="tabs" id="tabs"></nav><div class="editor-shell" id="editorShell"><pre class="highlight" id="highlight" aria-hidden="true"><code id="highlightCode"></code></pre><textarea class="editor" id="editor" spellcheck="true"></textarea></div><div class="actions"><button class="primary" id="save">Save file</button><button id="reload">Reload file</button><button id="format">Pretty-print JSON</button><button id="wrap">Wrap: On</button></div></section>
<aside class="panel side"><h2>Make targets</h2><div class="target-grid" id="targets"></div><pre class="status" id="status">Ready.</pre><iframe class="pdf" id="pdf" title="Generated resume PDF"></iframe></aside>
</main>
<script>
const state = { files: {}, active: null };
const tabs = document.querySelector('#tabs'), editor = document.querySelector('#editor'), statusBox = document.querySelector('#status'), highlightEl = document.querySelector('#highlight'), highlightCode = document.querySelector('#highlightCode'), formatBtn = document.querySelector('#format'), editorShell = document.querySelector('#editorShell'), wrapBtn = document.querySelector('#wrap');
let wrapEnabled = true;
function toggleWrap() { wrapEnabled = !wrapEnabled; editorShell.classList.toggle('nowrap', !wrapEnabled); wrapBtn.textContent = wrapEnabled ? 'Wrap: On' : 'Wrap: Off'; }
function escapeHtml(str) { return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function renderHighlight() { const isJson = state.active && state.active.endsWith('.json'); const pattern = isJson ? /"(?:[^"\\\\]|\\\\.)*"(?=\\s*:)|\\\\(?:[a-zA-Z@]+\\*?|[^a-zA-Z@\\\\])/g : /\\\\(?:[a-zA-Z@]+\\*?|[^a-zA-Z@\\\\])/g; const text = editor.value; let html = '', last = 0, match; while ((match = pattern.exec(text))) { const cls = match[0][0] === '"' ? 'key' : 'cmd'; html += escapeHtml(text.slice(last, match.index)) + `<span class="${cls}">${escapeHtml(match[0])}</span>`; last = match.index + match[0].length; } highlightCode.innerHTML = html + escapeHtml(text.slice(last)) + '\\n'; }
async function request(url, options) { const response = await fetch(url, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data; }
function renderTabs() { tabs.innerHTML = ''; Object.keys(state.files).forEach(name => { const button = document.createElement('button'); button.className = 'tab' + (name === state.active ? ' active' : ''); button.textContent = name; button.onclick = () => selectFile(name); tabs.append(button); }); }
function updateFormatButton() { formatBtn.style.display = state.active && state.active.endsWith('.json') ? '' : 'none'; }
function selectFile(name) { if (state.active) state.files[state.active] = editor.value; state.active = name; editor.value = state.files[name]; renderTabs(); renderHighlight(); updateFormatButton(); }
async function loadFiles() { const data = await request('/api/files'); state.files = data.files; state.active = Object.keys(state.files)[0]; editor.value = state.files[state.active]; renderTabs(); renderHighlight(); updateFormatButton(); }
async function save() { state.files[state.active] = editor.value; if (state.active.endsWith('.json')) { try { JSON.parse(editor.value); } catch (error) { statusBox.textContent = `Cannot save ${state.active}: invalid JSON — ${error.message}`; return; } } const data = await request('/api/save', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:state.active, content:editor.value}) }); statusBox.textContent = data.message; }
function formatJson() { try { editor.value = JSON.stringify(JSON.parse(editor.value), null, 2); state.files[state.active] = editor.value; renderHighlight(); statusBox.textContent = `Formatted ${state.active}. Click "Save file" to persist.`; } catch (error) { statusBox.textContent = `Cannot format ${state.active}: ${error.message}`; } }
async function run(target) { state.files[state.active] = editor.value; statusBox.textContent = `Running make ${target}...`; try { const data = await request('/api/make', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target}) }); statusBox.textContent = data.output; if (target === 'build' || target === 'user') document.querySelector('#pdf').src = '/output/resume.pdf?ts=' + Date.now(); } catch (error) { statusBox.textContent = error.message; } }
editor.addEventListener('input', renderHighlight);
editor.addEventListener('scroll', () => { highlightEl.scrollTop = editor.scrollTop; highlightEl.scrollLeft = editor.scrollLeft; });
document.querySelector('#save').onclick = save; document.querySelector('#reload').onclick = loadFiles; document.querySelector('#openPdf').onclick = () => window.open('/output/resume.pdf', '_blank'); formatBtn.onclick = formatJson; wrapBtn.onclick = toggleWrap;
request('/api/targets').then(data => data.targets.forEach(target => { const button = document.createElement('button'); button.textContent = 'make ' + target; button.onclick = () => run(target); document.querySelector('#targets').append(button); })).catch(error => statusBox.textContent = error.message);
loadFiles().catch(error => statusBox.textContent = error.message);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/files":
            self.send_json({"files": {name: (INPUT_DIR / name).read_text(encoding="utf-8") for name in EDITABLE_FILES}})
        elif path == "/api/targets":
            self.send_json({"targets": MAKE_TARGETS})
        elif path == "/output/resume.pdf":
            pdf = OUTPUT_DIR / "resume.pdf"
            if not pdf.exists():
                self.send_json({"error": "Build the resume before viewing the PDF."}, HTTPStatus.NOT_FOUND)
                return
            body = pdf.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if path == "/api/save":
                name, content = payload["name"], payload["content"]
                if name not in EDITABLE_FILES or not isinstance(content, str):
                    raise ValueError("Invalid input file")
                (INPUT_DIR / name).write_text(content, encoding="utf-8")
                self.send_json({"message": f"Saved input/{name}."})
            elif path == "/api/make":
                target = payload["target"]
                if target not in MAKE_TARGETS:
                    raise ValueError("Invalid Make target")
                result = subprocess.run(["make", target], cwd=ROOT, capture_output=True, text=True, check=False)
                output = result.stdout + result.stderr
                if result.returncode:
                    self.send_json({"error": output or f"make {target} failed"}, HTTPStatus.BAD_REQUEST)
                else:
                    self.send_json({"output": output or f"make {target} completed."})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


def open_browser(url):
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass  # no browser available (e.g. running inside the docker-editor container)


def main():
    port = int(os.environ.get("RESUME_EDITOR_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Resume editor: {url}")
    threading.Timer(0.5, open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
