"""Stdlib-only HTTP server for the virtual panel viewer.

Runs on daemon threads (ThreadingHTTPServer); the panel owns the main thread.
No dependencies beyond the standard library — keeping the harness install
surface at "pip install Pillow".
"""
import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    vp = None  # VirtualPanel, set by start_in_thread

    # -- helpers -------------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt, *args):  # quiet: journald-style noise not wanted
        pass

    # -- GET -----------------------------------------------------------------

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = {}
        for pair in query.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                params[k] = v
        try:
            if path == "/frame.png":
                self._get_frame(params)
            elif path == "/events":
                self._get_events()
            elif path == "/state":
                self._send_json(self.vp.state())
            else:
                self._get_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _get_frame(self, params):
        min_seq = params.get("min_seq")
        if min_seq is not None:
            timeout = int(params.get("timeout_ms", "10000")) / 1000.0
            self.vp.frames.wait_for_seq(int(min_seq), timeout)
        data, seq = self.vp.frames.get_png()
        self._send(200, data, "image/png", extra={"X-Frame-Seq": str(seq)})

    def _get_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.vp.frames.subscribe()
        try:
            # Prime the client with the current state immediately.
            self._sse_write("state", self.vp.state())
            seq = self.vp.frames.seq
            if seq:
                self._sse_write("frame", {"seq": seq})
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                if item["event"] == "frame":
                    self._sse_write("frame", {"seq": item["seq"], "w": item["w"],
                                              "h": item["h"]})
                else:
                    self._sse_write("state", item["state"])
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.vp.frames.unsubscribe(q)

    def _sse_write(self, event: str, obj) -> None:
        payload = "event: %s\ndata: %s\n\n" % (event, json.dumps(obj))
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def _get_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        # Path traversal guard: resolve inside WEB_ROOT only.
        candidate = os.path.normpath(os.path.join(WEB_ROOT, path.lstrip("/")))
        if not candidate.startswith(os.path.abspath(WEB_ROOT) + os.sep):
            self._send_json({"error": "not found"}, 404)
            return
        if not os.path.isfile(candidate):
            self._send_json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(candidate)[1].lower()
        with open(candidate, "rb") as fh:
            self._send(200, fh.read(), _CONTENT_TYPES.get(ext, "application/octet-stream"))

    # -- POST ----------------------------------------------------------------

    def do_POST(self):
        try:
            body = self._read_json()
            if self.path == "/mqtt":
                payload = body.get("payload", "")
                if isinstance(payload, (dict, list)):
                    payload = json.dumps(payload)
                self.vp.inject_mqtt(body["topic"], payload,
                                    retain=bool(body.get("retain", False)),
                                    qos=int(body.get("qos", 0)))
                self._send_json({"ok": True})
            elif self.path == "/touch":
                self.vp.tap(float(body["x"]), float(body["y"]))
                self._send_json({"ok": True})
            elif self.path == "/broker/drop":
                self.vp.broker.drop_client()
                self._send_json({"ok": True})
            elif self.path == "/broker/restart":
                self.vp.broker.restart_broker()
                self._send_json({"ok": True})
            elif self.path == "/panel/shutdown":
                self.vp.request_shutdown()
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._send_json({"error": repr(e)}, 500)


def start_in_thread(vp, bind: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"vp": vp})
    httpd = ThreadingHTTPServer((bind, port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever,
                              name="virtual-http", daemon=True)
    thread.start()
    return httpd
