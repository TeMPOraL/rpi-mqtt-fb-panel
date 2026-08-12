"""Pyodide bootstrap: run the unmodified panel inside a Web Worker.

Executed by virtual/web/js/worker_panel.js after it has written the panel
sources, the virtual package, and a font into the Pyodide filesystem. The
worker provides three JS globals: `vpConfig` (env + fb/touch settings),
`vpPostFrame(u8, w, h)`, `vpPostState(json_str)`, and the SharedArrayBuffer
views `vpSabI32` / `vpSabU8` used as the browser -> panel input ring.

Single-threaded model: the panel's main loop calls the fake evdev's
read_one() every ~10ms; our poll hook there drains the SAB ring (touch, mqtt,
control records), pumps the inline MQTT client (fake_paho.pump_all), and
periodically posts a state snapshot. The blocking main() therefore stays
byte-for-byte the real one — no cooperative rewrite.

SAB ring layout (written by transport_pyodide.js):
  Int32 header: [0] writeIdx (monotonic), [1] readIdx (monotonic), [2] dropped
  Data: 64 slots x 4096 bytes; each slot = u32 LE payload length + UTF-8 JSON.
  Records: {"t":"touch","x":..,"y":..} | {"t":"mqtt","topic":..,"payload":..,
  "retain":..} | {"t":"ctl","op":"drop"|"restart"|"shutdown"}
"""
import json
import os
import sys

import js  # Pyodide's JS bridge
from pyodide.ffi import to_js

SLOTS = 64
SLOT_SIZE = 4096

_config = _to_native = None


def _cfg():
    return js.vpConfig.to_py()


def boot():
    config = _cfg()

    # 1. Environment must be final before ANY panel/shim import
    #    (lcars_constants reads env and loads fonts at import time).
    for key, value in config["env"].items():
        os.environ[key] = str(value)

    repo_root = config.get("repo_root", "/panel")
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # 2. Broker + shims (inline paho: no threads in wasm).
    from virtual.shims.broker import MiniBroker
    from virtual.shims import install, fake_evdev, fake_paho

    broker = MiniBroker()

    def frame_sink(img):
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        js.vpPostFrame(to_js(img.tobytes()), img.width, img.height)

    touch_path = config["env"].get("TOUCH_DEVICE_PATH", "/dev/input/event0")
    abs_max = int(config.get("touch_abs_max", 4095))
    install.install_shims(broker, frame_sink,
                          int(config.get("fb_width", 720)),
                          int(config.get("fb_height", 480)),
                          int(config.get("fb_bpp", 32)),
                          touch_path, abs_max, paho_inline=True)

    # 3. Pyodide's signal module may reject handler registration; the panel
    #    installs SIGINT/SIGTERM handlers it never needs in a worker, so make
    #    signal.signal tolerant (shim-layer only; panel code untouched).
    import signal
    _orig_signal = signal.signal

    def _tolerant_signal(sig, handler):
        try:
            return _orig_signal(sig, handler)
        except (ValueError, OSError, RuntimeError) as e:
            print("virtual-pyodide: ignoring signal.signal(%r): %r" % (sig, e),
                  flush=True)
            return None
    signal.signal = _tolerant_signal

    # 4. Import the real panel.
    sys.argv = ["mqtt_fb_panel.py"]
    import mqtt_fb_panel as panel

    from virtual.harness import TouchInjector
    injector = TouchInjector(panel, touch_path, abs_max)

    # 5. Input ring reader + state pump, driven from the evdev poll hook.
    state_holder = {"tick": 0, "last": None}
    availability_topic = os.environ.get("MQTT_AVAILABILITY_TOPIC", "")
    mode_topic = os.environ.get("MQTT_MODE_TOPIC", "")
    client_id = os.environ.get("MQTT_CLIENT_ID", "")

    def snapshot():
        retained = broker.retained_snapshot()
        client = getattr(panel, "mqtt_client", None)
        lc = sys.modules.get("lcars_constants")
        return {
            "mode": panel.current_display_mode,
            "connected": bool(client.is_connected()) if client else False,
            "subscriptions": broker.subscription_count(client_id),
            "availability": retained.get(availability_topic),
            "mode_retained": retained.get(mode_topic),
            "retained": retained,
            "panel_publishes": broker.panel_publishes(limit=15),
            "messages_in_store": len(panel.messages_store),
            "dims": {"logical_w": panel.WIDTH, "logical_h": panel.HEIGHT},
            "font": {"path": os.environ.get("LCARS_FONT_PATH", ""),
                     "fallback": bool(config.get("font_fallback", False)),
                     "bar_height": getattr(lc, "BAR_HEIGHT", None) if lc else None},
            "prefixes": {
                "topic": os.environ.get("MQTT_TOPIC_PREFIX", ""),
                "control": os.environ.get("MQTT_CONTROL_TOPIC_PREFIX", ""),
            },
        }

    def drain_ring():
        write_idx = js.Atomics.load(js.vpSabI32, 0)
        read_idx = js.Atomics.load(js.vpSabI32, 1)
        while read_idx < write_idx:
            slot = read_idx % SLOTS
            base = slot * SLOT_SIZE
            u8 = js.vpSabU8
            length = (u8[base] | (u8[base + 1] << 8) |
                      (u8[base + 2] << 16) | (u8[base + 3] << 24))
            length = min(length, SLOT_SIZE - 4)
            raw = bytes(u8.subarray(base + 4, base + 4 + length).to_py())
            read_idx += 1
            js.Atomics.store(js.vpSabI32, 1, read_idx)
            try:
                rec = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            kind = rec.get("t")
            if kind == "touch":
                injector.tap(rec["x"], rec["y"])
            elif kind == "mqtt":
                broker.inject(rec["topic"], rec.get("payload", ""),
                              retain=bool(rec.get("retain", False)))
            elif kind == "ctl":
                op = rec.get("op")
                if op == "drop":
                    broker.drop_client()
                elif op == "restart":
                    broker.restart_broker()
                elif op == "shutdown":
                    panel._shutdown_requested = True

    def poll_hook():
        drain_ring()
        fake_paho.pump_all()
        state_holder["tick"] += 1
        if state_holder["tick"] % 25 == 0:  # ~4Hz at the 10ms loop cadence
            snap = snapshot()
            key = json.dumps(snap, sort_keys=True)
            if key != state_holder["last"]:
                state_holder["last"] = key
                js.vpPostState(key)

    fake_evdev.poll_hook = poll_hook

    # 6. Run the real main(); report the exit code to the page.
    exit_code = 0
    try:
        panel.main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    return exit_code
