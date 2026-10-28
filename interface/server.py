"""A small local web server (Python standard library only): serves the page in interface/web/ and answers its
requests by calling interface/api.py. It listens on 127.0.0.1 only, so nothing outside this computer can reach it."""
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from interface import api
from interface.tables import clean

WEB_DIR = Path(__file__).resolve().parent / "web"

POST_ROUTES = {
    "/api/case": lambda body: api.load_case(body["path"]),
    "/api/workbook": lambda body: api.inspect_workbook(body["path"], int(body["year"]), body.get("columns"),
                                                       body.get("run_type")),
    "/api/parameters": lambda body: api.parameters_for_page(body["run_type"], body["market"],
                                                            body.get("business_model", "direct_sales"),
                                                            body.get("overrides")),
    "/api/preview": lambda body: api.preview(body["case"]),
    "/api/run": lambda body: api.start_run(body["case"], body.get("output_dir") or None),
    "/api/open-folder": lambda body: open_folder(body["path"]),
}


def open_folder(path: str) -> dict:
    folder = Path(path)
    if not folder.is_dir():
        return {"error": f"{folder} does not exist yet."}
    if sys.platform.startswith("win"):
        os.startfile(folder)   # noqa: S606 (local folder chosen by the user)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return {"opened": str(folder)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):   # keep the console for the model's own messages
        pass

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(clean(data), allow_nan=False).encode("utf-8"), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            if url.path == "/api/options":
                return self._json(api.options())
            if url.path == "/api/status":
                return self._json(api.run_status(int(query.get("since", ["0"])[0])))
            if url.path == "/api/results":
                return self._json(api.run_results())
            if url.path == "/api/download":
                path = api.result_file(query.get("kind", [""])[0])
                if not path or not path.is_file():
                    return self._json({"error": "No such file."}, 404)
                ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                return self._send(200, path.read_bytes(), ctype,
                                  {"Content-Disposition": f'attachment; filename="{path.name}"'})
            name = "index.html" if url.path in ("/", "") else unquote(url.path.lstrip("/"))
            file = (WEB_DIR / name).resolve()
            if WEB_DIR not in file.parents or not file.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            return self._send(200, file.read_bytes(), ctype)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            if url.path == "/api/upload":
                name = parse_qs(url.query).get("name", ["workbook.xlsx"])[0]
                return self._json(api.save_upload(name, raw))
            route = POST_ROUTES.get(url.path)
            if route is None:
                return self._json({"error": "Unknown request."}, 404)
            return self._json(route(json.loads(raw or b"{}")))
        except Exception as exc:
            traceback.print_exc()
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(port: int = 8775) -> ThreadingHTTPServer:
    """The server on the first free port from `port`."""
    for candidate in range(port, port + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
        except OSError:
            continue
    raise OSError(f"No free port between {port} and {port + 19}.")
