"""Headless-browser test of the live viewer (requires playwright + chromium).

Skipped automatically when playwright isn't installed, so the base test suite
stays runnable with just `pip install -r virtual/requirements.txt` + pytest.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_VIRTUAL = os.path.join(REPO_ROOT, "virtual", "run_virtual.py")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get_json(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=10) as r:
        return json.loads(r.read())


def _wait_until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError("condition not met within %.1fs" % timeout)


@pytest.fixture(scope="module")
def panel():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-u", RUN_VIRTUAL, "--no-respawn", "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_until(lambda: _get_json(port, "/state")["availability"] == "online",
                    timeout=20)
        yield port
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_viewer_end_to_end(panel, tmp_path):
    port = panel
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto("http://127.0.0.1:%d/" % port)

        # SSE delivers state + frames: chips update, screen img gets a src.
        page.wait_for_selector("#chip-avail.ok", timeout=15000)
        _wait_until(lambda: page.get_attribute("#screen", "src"))

        # Switch to events mode via the command button.
        page.click("button[data-cmd='mode-select'][data-payload='events']")
        _wait_until(lambda: _get_json(port, "/state")["mode"] == "events")

        # Sample event button renders a new message.
        before = _get_json(port, "/state")["messages_in_store"]
        page.click("button.sample[data-importance='warning']")
        _wait_until(lambda: _get_json(port, "/state")["messages_in_store"] == before + 1)

        # Click the on-screen CLOCK button through the scaled <img>.
        img = page.locator("#screen")
        box = img.bounding_box()
        state = _get_json(port, "/state")
        w, h = state["dims"]["logical_w"], state["dims"]["logical_h"]
        page.mouse.click(box["x"] + 630 * box["width"] / w,
                         box["y"] + 463 * box["height"] / h)
        _wait_until(lambda: _get_json(port, "/state")["mode"] == "clock")

        # Broker restart via UI: availability must come back online.
        page.click("#btn-broker-restart")
        _wait_until(lambda: _get_json(port, "/state")["availability"] == "online")

        page.screenshot(path=str(tmp_path / "viewer.png"), full_page=True)
        browser.close()
