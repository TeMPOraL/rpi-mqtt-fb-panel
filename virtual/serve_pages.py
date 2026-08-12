#!/usr/bin/env python3
"""Static server for the repo root with cross-origin-isolation headers.

    python3 virtual/serve_pages.py [--port 8750]

Serves the same layout GitHub Pages does ("deploy from branch /(root)") but
adds COOP/COEP headers directly, so `virtual/web/panel.html` gets
SharedArrayBuffer without the coi-serviceworker reload dance. Useful for
local testing of the in-browser (Pyodide) panel and for headless e2e runs.
"""
import argparse
import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class COIHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        # Pyodide assets come from the jsdelivr CDN; CORP-tag our own
        # responses and let crossorigin fetches through.
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8750)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    handler = functools.partial(COIHandler, directory=REPO_ROOT)
    httpd = ThreadingHTTPServer((args.bind, args.port), handler)
    print("serving %s with COI headers at http://%s:%d/ "
          "(panel: /virtual/web/panel.html)" % (REPO_ROOT, args.bind, args.port),
          flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
