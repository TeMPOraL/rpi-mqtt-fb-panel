#!/usr/bin/env python3
"""Mirror the minimal Pyodide distribution subset into virtual/.pyodide-dist/.

Used for hermetic testing (`panel.html?pyodide=local`) and optional
self-hosting; the production page defaults to the pinned CDN. Downloads only
what the in-browser panel needs: core runtime + the Pillow wheel.
"""
import json
import os
import sys
import urllib.request

VERSION = "v314.0.4"  # keep in sync with PYODIDE_VERSION in worker_panel.js
BASE = "https://cdn.jsdelivr.net/pyodide/%s/full/" % VERSION
CORE_FILES = ["pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
              "python_stdlib.zip", "pyodide-lock.json"]

DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pyodide-dist")


def fetch(name):
    dest = os.path.join(DEST, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print("have %s" % name)
        return
    print("fetching %s..." % name, flush=True)
    with urllib.request.urlopen(BASE + name, timeout=120) as r:
        data = r.read()
    with open(dest, "wb") as fh:
        fh.write(data)
    print("  %d bytes" % len(data))


def main():
    os.makedirs(DEST, exist_ok=True)
    for name in CORE_FILES:
        fetch(name)
    with open(os.path.join(DEST, "pyodide-lock.json")) as fh:
        lock = json.load(fh)
    pillow = lock["packages"].get("pillow") or lock["packages"].get("Pillow")
    if not pillow:
        sys.exit("pillow not found in pyodide-lock.json")
    fetch(pillow["file_name"])
    for dep in pillow.get("depends", []):
        info = lock["packages"].get(dep)
        if info:
            fetch(info["file_name"])
    print("done: %s" % DEST)


if __name__ == "__main__":
    main()
