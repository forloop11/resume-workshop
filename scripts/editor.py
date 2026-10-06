#!/usr/bin/env python3
"""Local browser editor for input files and Makefile targets.

A small Flask app: templates/editor.html is the page (with a drag-and-drop
block editor for resume.json in static/blocks.js), and the JSON routes
below read/write the files in input/ and run the Makefile targets. Unlike
the generator scripts, this needs Flask (`pip install -r requirements.txt`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

try:
    from flask import Flask, jsonify, render_template, request, send_file
except ImportError:
    sys.exit("The editor needs Flask: pip install -r requirements.txt")

from generate_resume import SECTIONS

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
EDITABLE_FILES = ("format.tex", "header.yaml", "geometry.yaml", "section_order.yaml", "resume.json")
MAKE_TARGETS = ("build", "user")

app = Flask(__name__)


def json_payload():
    """The request's JSON object body; raises ValueError if it isn't one."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object body")
    return payload


@app.errorhandler(KeyError)
@app.errorhandler(ValueError)
def bad_request(error):
    return jsonify(error=str(error)), 400


@app.get("/")
def index():
    # SECTIONS is every section generate_resume.py knows how to render, so
    # the block editor offers exactly those in its section-order list.
    return render_template("editor.html", config={"sections": SECTIONS})


@app.get("/api/files")
def files():
    return jsonify(files={name: (INPUT_DIR / name).read_text(encoding="utf-8") for name in EDITABLE_FILES})


@app.get("/api/targets")
def targets():
    return jsonify(targets=MAKE_TARGETS)


@app.get("/output/resume.pdf")
def resume_pdf():
    pdf = OUTPUT_DIR / "resume.pdf"
    if not pdf.exists():
        return jsonify(error="Build the resume before viewing the PDF."), 404
    return send_file(pdf, mimetype="application/pdf", max_age=0)


@app.post("/api/save")
def save():
    payload = json_payload()
    name, content = payload["name"], payload["content"]
    if name not in EDITABLE_FILES or not isinstance(content, str):
        raise ValueError("Invalid input file")
    (INPUT_DIR / name).write_text(content, encoding="utf-8")
    return jsonify(message=f"Saved input/{name}.")


@app.post("/api/make")
def make():
    target = json_payload()["target"]
    if target not in MAKE_TARGETS:
        raise ValueError("Invalid Make target")
    result = subprocess.run(["make", target], cwd=ROOT, capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    if result.returncode:
        return jsonify(error=output or f"make {target} failed"), 400
    return jsonify(output=output or f"make {target} completed.")


def open_browser(url):
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass  # no browser available (e.g. running inside the docker-editor container)


def main():
    port = int(os.environ.get("RESUME_EDITOR_PORT", "8765"))
    url = f"http://127.0.0.1:{port}/"
    print(f"Resume editor: {url}")
    threading.Timer(0.5, open_browser, args=(url,)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
