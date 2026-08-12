#!/usr/bin/env python3
"""Headless scenario runner + image comparison for the virtual panel.

    python3 virtual/snapshot.py run virtual/scenarios/smoke.json --out virtual/out/smoke/
    python3 virtual/snapshot.py run ... --record        # also save every frame + timeline
    python3 virtual/snapshot.py compare a.png b.png [--threshold 3.0] [--heatmap diff.png]

Scenario JSON:
  {
    "name": "...", "description": "...",
    "env": {"STARTING_MODE": "events"},          # optional overrides
    "steps": [
      {"do": "wait", "ms": 300},
      {"do": "mqtt", "topic": "home/alert/x", "payload": {...}|"raw", "retain": false},
      {"do": "touch", "x": 630, "y": 463},
      {"do": "wait_frame", "timeout_ms": 3000},
      {"do": "wait_state", "until": {"mode": "events"}, "timeout_ms": 5000},
      {"do": "broker_drop"}, {"do": "broker_restart"},
      {"do": "capture", "name": "final", "source": "frame"|"panel"}
    ]
  }

capture source "panel" copies panel.last_rendered_img — the same artifact the
device's `screenshot` control command saves, for apples-to-apples comparison.
Golden determinism: use events mode and explicit `timestamp` fields in
payloads; clock mode renders wall-clock time and cannot be golden-compared.
"""
import argparse
import json
import math
import os
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------
class ScenarioRunner:
    def __init__(self, vp, scenario, out_dir, record=False):
        self.vp = vp
        self.scenario = scenario
        self.out_dir = out_dir
        self.record = record
        self.captures = []      # (index, name, PIL image)
        self.timeline = []      # recorded events for the replayer
        self.frames = []        # (seq, t, PIL image) when recording
        self.error = None
        self._t0 = None
        self._baseline_seq = 0  # frame seq before the last stimulus step

    def _now_ms(self):
        return int((time.monotonic() - self._t0) * 1000)

    def _log_event(self, kind, detail):
        self.timeline.append({"t_ms": self._now_ms(), "type": kind, "detail": detail})

    def run_steps(self):
        try:
            self._wait_until(lambda s: s["availability"] == "online", 15000,
                             "panel never reached availability=online")
            self._t0 = time.monotonic()
            if self.record:
                def hook(img, seq):
                    self.frames.append((seq, self._now_ms(), img))
                self.vp.frames.on_frame_hook = hook
            for i, step in enumerate(self.scenario.get("steps", [])):
                self._run_step(i, step)
        except Exception as e:
            self.error = e
        finally:
            self.vp.frames.on_frame_hook = None
            self.vp.request_shutdown()

    def _run_step(self, i, step):
        do = step["do"]
        if do == "wait":
            time.sleep(step.get("ms", 100) / 1000.0)
        elif do == "mqtt":
            payload = step.get("payload", "")
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            self._baseline_seq = self.vp.frames.seq
            self.vp.inject_mqtt(step["topic"], payload,
                                retain=bool(step.get("retain", False)))
            self._log_event("mqtt", {"topic": step["topic"], "payload": payload[:200]})
        elif do == "touch":
            self._baseline_seq = self.vp.frames.seq
            self.vp.tap(step["x"], step["y"])
            self._log_event("touch", {"x": step["x"], "y": step["y"]})
        elif do == "wait_frame":
            # "At least one frame since the last stimulus step" (mqtt/touch/
            # chaos); passes immediately if one already rendered — waiting on
            # frames *after* the wait starts would deadlock in events mode,
            # which repaints only on stimulus.
            baseline = self._baseline_seq
            timeout = step.get("timeout_ms", 3000) / 1000.0
            if self.vp.frames.wait_for_seq(baseline, timeout) <= baseline:
                raise AssertionError("step %d: no new frame within %.1fs" % (i, timeout))
        elif do == "wait_state":
            until = step["until"]
            self._wait_until(
                lambda s: all(s.get(k) == v for k, v in until.items()),
                step.get("timeout_ms", 5000),
                "step %d: state never matched %r" % (i, until))
        elif do == "broker_drop":
            self._baseline_seq = self.vp.frames.seq
            self.vp.broker.drop_client()
            self._log_event("broker", {"op": "drop"})
        elif do == "broker_restart":
            self._baseline_seq = self.vp.frames.seq
            self.vp.broker.restart_broker()
            self._log_event("broker", {"op": "restart"})
        elif do == "capture":
            name = step.get("name", "capture%d" % i)
            source = step.get("source", "frame")
            if source == "panel":
                img = self.vp.panel.last_rendered_img
                img = img.copy() if img is not None else None
            else:
                img, _seq = self.vp.frames.get_image()
            if img is None:
                raise AssertionError("step %d: nothing to capture yet" % i)
            self.captures.append((i, name, img))
            self._log_event("capture", {"name": name})
        else:
            raise ValueError("unknown step %r" % do)

    def _wait_until(self, predicate, timeout_ms, message):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if predicate(self.vp.state()):
                return
            time.sleep(0.05)
        raise AssertionError(message)


def cmd_run(args):
    with open(args.scenario, "r", encoding="utf-8") as fh:
        scenario = json.load(fh)
    os.makedirs(args.out, exist_ok=True)

    from virtual.harness import VirtualPanel
    vp = VirtualPanel(env_file=args.env, extra_env=scenario.get("env"))
    panel = vp.import_panel([])

    runner = ScenarioRunner(vp, scenario, args.out, record=args.record)
    thread = threading.Thread(target=runner.run_steps, name="scenario", daemon=True)
    thread.start()

    exit_code = 0
    try:
        panel.main()  # blocks on the main thread until the scenario shuts it down
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    thread.join(timeout=10)

    for idx, name, img in runner.captures:
        path = os.path.join(args.out, "%03d_%s.png" % (idx, name))
        img.save(path)
        print("virtual: wrote %s" % path, flush=True)

    state = vp.state()
    state["scenario"] = scenario.get("name")
    state["panel_exit_code"] = exit_code
    state["traffic_log"] = vp.broker.traffic_log()
    import PIL
    state["versions"] = {"python": sys.version.split()[0], "pillow": PIL.__version__}
    with open(os.path.join(args.out, "state.json"), "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)

    if args.record:
        frames_dir = os.path.join(args.out, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        manifest_frames = []
        for seq, t_ms, img in runner.frames:
            fname = "%05d.png" % seq
            img.save(os.path.join(frames_dir, fname))
            manifest_frames.append({"seq": seq, "t_ms": t_ms, "file": "frames/" + fname})
        manifest = {
            "name": scenario.get("name"),
            "description": scenario.get("description", ""),
            "dims": {"w": vp.fb_width, "h": vp.fb_height},
            "frames": manifest_frames,
            "events": runner.timeline,
        }
        with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        print("virtual: recorded %d frames + manifest.json" % len(manifest_frames),
              flush=True)

    if runner.error:
        print("virtual: SCENARIO FAILED: %r" % runner.error, flush=True)
        return 1
    print("virtual: scenario '%s' completed" % scenario.get("name"), flush=True)
    return 0


# ---------------------------------------------------------------------------
# Image comparison
# ---------------------------------------------------------------------------
def cmd_compare(args):
    from PIL import Image, ImageChops
    a = Image.open(args.a).convert("RGB")
    b = Image.open(args.b).convert("RGB")
    if a.size != b.size:
        print("size mismatch: %s vs %s" % (a.size, b.size))
        return 2
    diff = ImageChops.difference(a, b)
    hist = diff.histogram()  # 3 x 256
    npx = a.size[0] * a.size[1]
    sq_sum = 0
    changed = 0
    for band in range(3):
        for value, count in enumerate(hist[band * 256:(band + 1) * 256]):
            sq_sum += count * value * value
            if value > 0:
                changed += count
    rmse = math.sqrt(sq_sum / (npx * 3))
    changed_px = sum(1 for px in diff.getdata() if px != (0, 0, 0))
    print("RMSE: %.3f | changed pixels: %d / %d (%.2f%%)"
          % (rmse, changed_px, npx, 100.0 * changed_px / npx))
    if args.heatmap:
        heat = diff.point(lambda v: min(255, v * 8))
        heat.save(args.heatmap)
        print("heatmap written to %s" % args.heatmap)
    if args.threshold is not None and rmse > args.threshold:
        print("FAIL: RMSE %.3f > threshold %.3f" % (rmse, args.threshold))
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run a scenario headlessly")
    p_run.add_argument("scenario")
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--env", default=None)
    p_run.add_argument("--record", action="store_true",
                       help="save every frame + timeline manifest (for the web replayer)")
    p_cmp = sub.add_parser("compare", help="compare two PNGs (RMSE + heatmap)")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.add_argument("--threshold", type=float, default=None)
    p_cmp.add_argument("--heatmap", default=None)
    args = parser.parse_args()
    if args.cmd == "run":
        sys.exit(cmd_run(args))
    sys.exit(cmd_compare(args))


if __name__ == "__main__":
    main()
