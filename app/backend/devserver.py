#!/usr/bin/env python3
"""The editor's window in a web browser, without Tauri: for working on the
front end where the Tauri toolchain isn't installed, and for its tests.

    npm run build && python3 backend/devserver.py [port]

serves the built front end (app/dist) and answers its requests, POSTed to
/rpc, with the same Backend the Tauri app runs (server.py). It listens on
this machine only. What the Tauri shell adds -- the folder and file
dialogs -- is asked for here by typing a path.
"""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402

DIST = Path(__file__).resolve().parent.parent / "dist"


def handler(backend):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *arguments, **keywords):
            super().__init__(*arguments, directory=str(DIST), **keywords)

        def do_POST(self):
            if self.path != "/rpc":
                self.send_error(404)
                return
            replies = []
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            # One request, answered before this returns.
            request = json.loads(body)
            reply = {"id": request.get("id")}
            try:
                reply["result"] = getattr(backend, request["method"])(**(request.get("params") or {}))
            except server.Failure as error:
                reply["error"] = str(error)
            except Exception as error:
                reply["error"] = f"{type(error).__name__}: {error}"
            replies.append(json.dumps(reply, ensure_ascii=False).encode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(replies[0])))
            self.end_headers()
            self.wfile.write(replies[0])

        def log_message(self, *_):
            pass

    return Handler


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3210
    server.exit_on_signals()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler(server.Backend()))
    print(f"http://127.0.0.1:{port}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
