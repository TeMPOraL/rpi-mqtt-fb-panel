"""Integration: boot the real panel under the harness and drive it over HTTP.

Subprocess-based because panel.main() owns the main thread and module state
is not reusable across tests. One process per test class keeps it fast enough.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_VIRTUAL = os.path.join(REPO_ROOT, "virtual", "run_virtual.py")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=10) as r:
        return r.read()


def _get_json(port, path):
    return json.loads(_get(port, path))


def _post(port, path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _wait_until(predicate, timeout=10.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("condition not met within %.1fs" % timeout)


@pytest.fixture(scope="module")
def panel():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-u", RUN_VIRTUAL, "--no-respawn", "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_until(lambda: _try_state(port) is not None, timeout=20)
        _wait_until(lambda: _try_state(port).get("availability") == "online", timeout=10)
        yield {"port": port, "proc": proc}
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        # Attach output on failure diagnosis.
        print(out)


def _try_state(port):
    try:
        return _get_json(port, "/state")
    except Exception:
        return None


def test_boot_reaches_online_with_device_handshake(panel):
    state = _get_json(panel["port"], "/state")
    assert state["connected"] is True
    assert state["availability"] == "online"
    assert state["mode"] == "clock"           # STARTING_MODE parity
    assert state["mode_retained"] == "clock"  # retained mode published on connect
    assert state["dims"]["logical_w"] == 720 and state["dims"]["logical_h"] == 480


def test_clock_frames_tick(panel):
    seq1 = _get_json(panel["port"], "/state")["frame_seq"]
    time.sleep(2.5)
    seq2 = _get_json(panel["port"], "/state")["frame_seq"]
    assert seq2 >= seq1 + 2  # clock repaints every second


def test_frame_png_endpoint(panel):
    data = _get(panel["port"], "/frame.png")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_mqtt_event_and_mode_select(panel):
    port = panel["port"]
    _post(port, "/mqtt", {"topic": "lcars/alert-panel/mode-select", "payload": "events"})
    _wait_until(lambda: _get_json(port, "/state")["mode"] == "events")
    before = _get_json(port, "/state")["messages_in_store"]
    _post(port, "/mqtt", {"topic": "home/alert/test",
                          "payload": {"message": "hello", "source": "pytest",
                                      "importance": "info"}})
    _wait_until(lambda: _get_json(port, "/state")["messages_in_store"] == before + 1)


def test_touch_tap_switches_mode(panel):
    port = panel["port"]
    # In events mode the CLOCK button lives in the bottom bar right cluster.
    _post(port, "/mqtt", {"topic": "lcars/alert-panel/mode-select", "payload": "events"})
    _wait_until(lambda: _get_json(port, "/state")["mode"] == "events")
    _post(port, "/touch", {"x": 630, "y": 463})
    _wait_until(lambda: _get_json(port, "/state")["mode"] == "clock")
    # Touch-driven mode change republishes retained state.
    _wait_until(lambda: _get_json(port, "/state")["mode_retained"] == "clock")


def test_broker_restart_incident_regression(panel):
    """THE regression: broker restart wipes sessions; the hardened panel must
    resubscribe and keep receiving messages (it once stayed deaf for 10 days)."""
    port = panel["port"]
    _post(port, "/broker/restart", {})
    # NOTE: retained availability still reads "online" from before the restart
    # — the truthful "resubscribed" signal is the broker-side subscription
    # count going 0 -> 2 again.
    _wait_until(lambda: _get_json(port, "/state")["subscriptions"] == 2, timeout=15)
    before = _get_json(port, "/state")["messages_in_store"]
    _post(port, "/mqtt", {"topic": "home/alert/after-restart",
                          "payload": {"message": "delivered after broker restart",
                                      "source": "pytest", "importance": "info"}})
    _wait_until(lambda: _get_json(port, "/state")["messages_in_store"] == before + 1)


def test_broker_drop_fires_lwt_then_recovers(panel):
    port = panel["port"]
    _post(port, "/broker/drop", {})
    # LWT flips retained availability to offline, reconnect flips it back.
    _wait_until(lambda: _get_json(port, "/state")["availability"] == "online",
                timeout=15)
    publishes = _get_json(port, "/state")["panel_publishes"]
    assert any(e["origin"] == "lwt" and e["payload"] == "offline" for e in publishes)


def test_no_callback_api_version_attr():
    """The panel must take the paho 1.x constructor branch, as on the device."""
    sys.path.insert(0, REPO_ROOT)
    from virtual.shims import fake_paho
    assert not hasattr(fake_paho, "CallbackAPIVersion")
