# Virtual LCARS Panel

Run the **exact production panel code, unmodified**, without the Raspberry Pi:
the harness pre-inserts fake `framebuffer_utils`, `evdev` and `paho` modules
into `sys.modules` before importing `mqtt_fb_panel`, so the real
`/dev/fb0`/hardware modules are never even imported. Frames go through the same
rotate + RGB565 pipeline as the device and are served to a browser; MQTT is an
in-process mini-broker with synthetic controls; touch is injected through the
panel's own coordinate-transform code (numerically inverted).

## Quickstart

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r virtual/requirements.txt
# optional but recommended for fidelity — see virtual/fonts/README.md:
#   scp <user>@<panel-host>:/usr/share/fonts/truetype/dejavu/Swiss-911-*.ttf virtual/fonts/
python3 virtual/run_virtual.py
# open http://localhost:8724
```

From WSL2, `localhost` is forwarded automatically — open the URL in your
Windows browser.

`run_virtual.py` options: `--port N`, `--env FILE` (default `virtual/panel.env`
if present, else `virtual/panel.env.example`), `--no-respawn` (don't emulate
systemd `Restart=always` after the MQTT `restart` command), `--hold` (keep the
HTTP server up after the panel exits), and anything after `--` is passed to the
panel itself (e.g. `-- --debug`).

## The viewer

- Live screen (click = touch, mapped through the panel's real calibration).
- Buttons for control commands (`mode-select`, `clear-events`, `debug-layout`,
  `debug-touch`, `screenshot`, `restart`) and sample info/warning/error events.
- Free-form publish (topic / payload / retain).
- Broker chaos controls: **Drop connection** (LWT fires, panel auto-reconnects)
  and **Restart broker** (sessions wiped, retained kept — reproduces the 2026
  production incident; the hardened panel must resubscribe and come back).
- State panel: availability + mode retained values, retained-topic table,
  recent panel publishes.

## HTTP API (everything the viewer uses; also curl-friendly)

| Endpoint | Meaning |
|---|---|
| `GET /frame.png[?min_seq=N&timeout_ms=M]` | Latest frame; long-polls until seq > N |
| `GET /events` | SSE: `frame` and `state` events |
| `GET /state` | Mode, availability, retained table, panel publishes, dims, font |
| `POST /mqtt` `{topic,payload,retain?}` | Inject a publish (object payloads are JSON-encoded) |
| `POST /touch` `{x,y}` | Tap at logical screen coordinates |
| `POST /broker/drop` / `POST /broker/restart` | Chaos controls |
| `POST /panel/shutdown` | Ask the panel main loop to exit cleanly |

## Headless scenarios (regression + device comparison)

```sh
python3 virtual/snapshot.py run virtual/scenarios/broker_restart.json --out virtual/out/br/
python3 virtual/snapshot.py compare a.png b.png   # RMSE + diff heatmap
```

Scenario JSON drives timed MQTT/touch/chaos steps and named PNG captures
(`source: "panel"` captures `last_rendered_img` — the very artifact the
device's `screenshot` command saves, for apples-to-apples comparison).
`--record` additionally saves every frame + a timeline for the web replayer.

**Device comparison loop:** run a scenario virtually → run
`python3 virtual/replay_scenario.py <scenario> --host <broker>` (uses
`mosquitto_pub`; touch steps become prompts) → grab the device screenshot →
`snapshot.py compare`. Geometry should match exactly when using the same font;
small anti-aliasing differences remain (device renders with Pillow 8.1.2).

## The whole panel in your browser (Pyodide)

`virtual/web/panel.html` runs the **same unmodified panel code entirely
client-side**: Python + Pillow via Pyodide (pinned version, loaded from the
jsdelivr CDN, ~15MB on first visit then cached), the same shims, an inline
(single-threaded) broker mode, and the same viewer UI. No server, no install —
works straight from GitHub Pages:

```
https://<user>.github.io/rpi-mqtt-fb-panel/virtual/web/panel.html
```

- The real blocking `main()` runs in a module Web Worker; frames stream out
  via postMessage, input (touch/MQTT/chaos) goes in through a
  SharedArrayBuffer ring drained by the shims' evdev poll hook every 10ms.
- SharedArrayBuffer needs cross-origin isolation: the vendored
  `coi-serviceworker.js` provides it on Pages (the very first visit reloads
  itself once). Locally, `python3 virtual/serve_pages.py` serves the repo
  with proper COOP/COEP headers instead.
- Font: drop the device's Swiss911 `.ttf` onto the page once (persisted in
  your browser's IndexedDB only — never uploaded); DejaVu fallback otherwise.
- The broker-chaos buttons work here too — the 2026 incident is reproducible
  in a browser tab.
- Divergences vs. the local harness: single-threaded MQTT callback delivery
  (no cross-thread races; the CPython harness remains the threading-fidelity
  gate), and the panel restart command cold-restarts the whole worker.
- Hermetic testing / self-hosting: `python3 virtual/fetch_pyodide_dist.py`
  mirrors the runtime into `virtual/.pyodide-dist/` (gitignored), then
  `panel.html?pyodide=local` uses it instead of the CDN.

## Recordings on GitHub Pages (share without pulling)

`snapshot.py run --record` writes `virtual/recordings/<name>/`. Committed
recordings are replayable in any browser via
`virtual/web/replay.html?rec=<name>` — locally with
`python3 -m http.server` from the repo root, or on GitHub Pages
(one-time setup: repo Settings → Pages → Deploy from a branch → `master` +
`/(root)`; every push then auto-deploys):

```
https://<user>.github.io/rpi-mqtt-fb-panel/virtual/web/replay.html?rec=<name>
```

## Fidelity notes

- Geometry (bars, buttons, wrapping) derives from the font: use the device's
  Swiss911 file (see `virtual/fonts/README.md`). With the DejaVu fallback the
  panel runs but comparisons are invalid.
- Colors are exact: the device framebuffer runs at 32bpp (its 16bpp/RGB565
  code path turned out to be dead code — see `virtual/PLAN.md` observations),
  so no quantization applies. A 16bpp mode (`VIRTUAL_FB_BPP=16`) exists for
  hypothetical future displays.
- MQTT callbacks are delivered from a dedicated thread, like paho's network
  thread on the device — threading behavior is preserved, not serialized.
- Known divergence: the device runs Pillow 8.1.2; modern Pillow may anti-alias
  glyphs slightly differently. Layout geometry is unaffected.
