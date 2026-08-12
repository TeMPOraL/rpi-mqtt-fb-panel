# Virtual Panel Subproject Plan

Development harness that runs the unmodified panel code off-device. See
`virtual/README.md` for usage. Constraint honored throughout: **no changes to
existing panel files** — everything lives under `virtual/`, wired in via
`sys.modules` pre-insertion (no path shadowing, so on-device runs can never be
affected).

## Milestones

*   [x] **M0 — Scaffolding:** tree, docs, `panel.env.example`, vendored
    DejaVuSans + license, gitignore.
*   [x] **M1 — Shims + harness (headless):**
    *   [x] `shims/rgb565.py` — LUT quantization for the (dead-code, see observations) 16bpp branch; validated against canonical 5/6/5 math.
    *   [x] `shims/broker.py` — MiniBroker: wildcard matching, retained store, LWT, per-client delivery thread, drop/restart chaos controls, truthful subscription count.
    *   [x] `shims/fake_paho.py` — paho-mqtt 1.5.x v1-API subset (deliberately **no** `CallbackAPIVersion` attribute; guarded by test).
    *   [x] `shims/fake_evdev.py` — faithful python-evdev shapes; tap event queue.
    *   [x] `shims/fake_framebuffer.py` — mirrors the real module exactly (push guard, call-time rotation, WIDTH/HEIGHT expression, double-close semantics). Defaults 720x480x32.
    *   [x] `harness.py` — env/font/boot glue, FrameStore, touch inverse-affine injector, state snapshots.
    *   [x] `run_virtual.py` — entry point + `Restart=always` re-exec emulation.
    *   [x] Tests (29 + Playwright): broker semantics; full boot handshake reaching retained "online"; touch inject flips mode + republishes retained state; broker-restart incident regression.
*   [x] **M2 — HTTP server + live viewer:** stdlib server (frames + long-poll, SSE, injection, chaos), vanilla-JS viewer; Playwright e2e (SSE chips, scaled click-to-touch, broker restart via UI).
*   [x] **M3 — Scenarios:** `snapshot.py` runner + `compare` (golden determinism: two runs at RMSE 0.000), scenario files incl. `broker_restart.json` incident regression, `replay_scenario.py` for device-side replay.
*   [ ] **M4 — Fidelity gate (needs user):** Swiss911 in `virtual/fonts/`; compare virtual `BAR_HEIGHT` and golden scenario renders against the device (see Open items).
*   [x] **M5 — Phase 2a:** `--record`, committed demo recording, `web/replay.html` replayer (play/scrub/event markers), Pages setup docs; Playwright-verified against a repo-root static server.
*   [ ] **M6 — Phase 2b (future):** interactive in-browser panel via Pyodide (same shims; worker + SharedArrayBuffer input ring + coi-serviceworker; broker inline-dispatch mode; cooperative-driver fallback with source-hash drift alarm).

## Decision log

- **RGB565 via `Image.point` LUT** (not per-pixel Python, not `tobytes` round-trip in production): C-speed, byte-exact — equivalence enforced by test against the device's actual conversion path.
- **Per-client broker delivery thread**: preserves the device's "network thread mutates shared state while the main loop renders" semantics. Harness locks only its own state; panel calls are never serialized.
- **`loop_stop()` ⇒ abnormal drop ⇒ LWT fires**: approximates the device, where `bye()` stops the loop and process exit kills TCP without DISCONNECT, so the broker publishes retained `offline`.
- **`restart` command ⇒ `os.execv` re-exec**: emulates systemd `Restart=always` with a genuinely fresh process (panel module state is not safely reloadable in-process).
- **Determinism policy**: golden scenarios use events mode with explicit `timestamp` payload fields; clock mode is not golden-able (renders `datetime.now()`).
- **Live vs retained delivery flags**: live fan-out delivers `retain=0` even for retained publishes; retained-store delivery on subscribe uses `retain=1` [MQTT-3.3.1-9]. This is what makes the panel's "ignore RETAINED restart" guard behave identically to Mosquitto.
- **Touch injection inverts the real transform numerically** (affine fit from 3 probe points through `_transform_touch_coordinates`): zero logic duplication, stays correct if calibration constants change.

## Observations about the panel code (not fixed here; candidates for later)

- **The 16bpp framebuffer branch is dead code**: `framebuffer_utils.push()`
  does `img.tobytes("raw", "BGR;16")` from an RGB image, but no Pillow version
  (checked 8.1.2 source, 9.5, 11, 12) has an RGB→BGR;16 packer — that branch
  raises `ValueError: No packer found`. Since the device demonstrably works,
  its framebuffer must report bpp=32 (RPi HDMI/composite default) and run the
  BGRA branch. Consequence: virtual fb defaults to 32bpp, colors are exact
  (no 565 quantization). If a 16bpp display is ever used, the panel's 16bpp
  branch needs an actual fix (e.g. manual 565 packing).

- **evdev auto-detect can never match**: `_initialize_touch_device` checks `ecodes.ABS_X in cap[ecodes.EV_ABS]`, but python-evdev returns `EV_ABS` capabilities as `(code, AbsInfo)` tuples, so the membership test compares int vs tuple — on real hardware too. `TOUCH_DEVICE_PATH` must therefore be set explicitly (the harness env does).
- **numpy is a stale dependency**: not imported anywhere in the panel source.
- `framebuffer_utils.FB.close()` raises `EBADF` on a second call (stale fd); the panel avoids it via the `_exit_in_progress` latch. The fake mirrors this so future double-close bugs reproduce virtually.

## Open items

- [ ] M4: record device `BAR_HEIGHT` (`python3 -c "import lcars_constants as lc; print(lc.BAR_HEIGHT)"` on the Pi) and compare.
- [ ] Optional: try `Pillow<10` locally and record whether AA matches the device better.
- [ ] M6: pin Pyodide version; needs `cdn.jsdelivr.net` allowed in the sandbox network policy for e2e.
