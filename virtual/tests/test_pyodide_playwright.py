"""Headless e2e of the in-browser (Pyodide) panel.

Requires playwright + the local Pyodide mirror:
    python3 virtual/fetch_pyodide_dist.py
Skipped automatically when either is missing. Uses the mirror rather than the
CDN so the test is hermetic (and because sandboxed environments may not reach
the CDN); the production page defaults to the pinned CDN.
"""
import os
import socket
import subprocess
import sys
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(REPO_ROOT, "virtual", ".pyodide-dist")

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(DIST, "pyodide.mjs")),
    reason="local Pyodide mirror missing (run virtual/fetch_pyodide_dist.py)")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO_ROOT, "virtual", "serve_pages.py"),
         "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    yield port
    proc.terminate()


def test_pyodide_panel_end_to_end(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        page.goto("http://127.0.0.1:%d/virtual/web/panel.html?pyodide=local" % server)
        assert page.evaluate("window.crossOriginIsolated") is True

        # Boot: wasm init + package load + panel start (generous timeout).
        page.wait_for_selector("#chip-avail.ok", timeout=120000)

        # Clock frames tick.
        page.wait_for_function(
            "parseInt(document.getElementById('chip-seq').textContent.split(' ')[1]) >= 1",
            timeout=30000)
        seq1 = page.evaluate(
            "parseInt(document.getElementById('chip-seq').textContent.split(' ')[1])")
        time.sleep(2.5)
        seq2 = page.evaluate(
            "parseInt(document.getElementById('chip-seq').textContent.split(' ')[1])")
        assert seq2 >= seq1 + 2

        # MQTT through the SAB ring: mode switch + a stored message.
        page.click("button[data-cmd='mode-select'][data-payload='events']")
        page.wait_for_function("window.__vpState && window.__vpState.mode === 'events'",
                               timeout=20000)
        page.click("button.sample[data-importance='error']")
        page.wait_for_function(
            "window.__vpState && window.__vpState.messages_in_store >= 1", timeout=20000)

        # Touch through the SAB ring + the panel's real transform.
        box = page.locator("#screen").bounding_box()
        page.mouse.click(box["x"] + 630 * box["width"] / 720,
                         box["y"] + 463 * box["height"] / 480)
        page.wait_for_function("window.__vpState && window.__vpState.mode === 'clock'",
                               timeout=20000)

        # The production-incident regression, in a browser tab: after a broker
        # restart the panel must resubscribe and republish availability.
        page.click("#btn-broker-restart")
        page.wait_for_function("window.__vpState && window.__vpState.subscriptions === 2",
                               timeout=30000)
        page.wait_for_function(
            "window.__vpState && window.__vpState.panel_publishes.filter("
            "e => e.topic.includes('availability')).length >= 2", timeout=30000)
        browser.close()
