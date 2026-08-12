"""Virtual panel harness: env/font/boot glue, frame store, touch injection.

Used by run_virtual.py (interactive HTTP viewer) and snapshot.py (headless
scenarios). The panel's main() must run on the process main thread (it
installs signal handlers); everything here is designed to be driven from
other threads without ever blocking or serializing the panel's own threads.
"""
import glob
import os
import queue
import sys
import threading
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Environment / font resolution (must all happen before panel imports)
# ---------------------------------------------------------------------------
def load_env_file(path: str) -> None:
    """KEY=VALUE loader; values already present in os.environ win, so shell
    overrides beat the file (same precedence users expect from systemd
    EnvironmentFile + manual runs)."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.split("#", 1)[0].strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def resolve_font() -> Tuple[str, bool]:
    """Pick the font per virtual/fonts/README.md order; export LCARS_FONT_PATH.

    Returns (absolute_path, fallback_used)."""
    explicit = os.environ.get("LCARS_FONT_PATH")
    if explicit:
        return os.path.abspath(explicit), False
    fonts_dir = os.path.join(REPO_ROOT, "virtual", "fonts")
    swiss = sorted(glob.glob(os.path.join(fonts_dir, "Swiss-911*.ttf")))
    if swiss:
        os.environ["LCARS_FONT_PATH"] = swiss[0]
        return swiss[0], False
    dejavu = os.path.join(fonts_dir, "DejaVuSans.ttf")
    os.environ["LCARS_FONT_PATH"] = dejavu
    print("virtual: WARNING - LCARS font (Swiss911) not found in virtual/fonts/; "
          "using vendored DejaVuSans. The panel runs, but layout geometry "
          "(BAR_HEIGHT etc.) differs from the device: fidelity comparisons "
          "are INVALID. See virtual/fonts/README.md.", flush=True)
    return dejavu, True


# ---------------------------------------------------------------------------
# Frame store
# ---------------------------------------------------------------------------
class FrameStore:
    """Latest-frame holder. on_frame() is called from panel threads and must
    never block: it stores a reference, bumps seq and notifies. PNG encoding
    happens lazily on consumer threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._img: Optional[Image.Image] = None
        self._seq = 0
        self._png_cache: Optional[Tuple[int, bytes]] = None
        self._subscribers: List["queue.Queue"] = []
        self.on_frame_hook = None  # extra sink (recording); called on panel thread

    def on_frame(self, img: Image.Image) -> None:
        with self._lock:
            self._img = img
            self._seq += 1
            self._png_cache = None
            seq = self._seq
            self._cond.notify_all()
            for q in self._subscribers:
                try:
                    q.put_nowait({"event": "frame", "seq": seq,
                                  "w": img.width, "h": img.height, "t": time.time()})
                except queue.Full:
                    pass
        hook = self.on_frame_hook
        if hook is not None:
            hook(img, seq)

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def wait_for_seq(self, min_seq: int, timeout: float) -> int:
        """Block until seq > min_seq (or timeout). Returns current seq."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._seq <= min_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    break
            return self._seq

    def get_png(self) -> Tuple[bytes, int]:
        with self._lock:
            img, seq = self._img, self._seq
            cache = self._png_cache
        if img is None:
            # 1x1 placeholder before the first frame.
            img, seq = Image.new("RGB", (1, 1)), 0
        if cache is not None and cache[0] == seq:
            return cache[1], seq
        buf = BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        with self._lock:
            if seq == self._seq:
                self._png_cache = (seq, data)
        return data, seq

    def get_image(self) -> Tuple[Optional[Image.Image], int]:
        with self._lock:
            return self._img, self._seq

    def subscribe(self) -> "queue.Queue":
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def notify_state(self, state: Dict[str, Any]) -> None:
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait({"event": "state", "state": state, "t": time.time()})
                except queue.Full:
                    pass


# ---------------------------------------------------------------------------
# Touch injection via numeric inversion of the panel's own transform
# ---------------------------------------------------------------------------
class TouchInjector:
    """Derives the inverse of panel._transform_touch_coordinates numerically.

    The forward transform (rotation + calibration scaling) is affine, so
    sampling it at three non-collinear raw points yields the exact matrix; we
    never duplicate its logic, so calibration-constant changes stay covered."""

    def __init__(self, panel_module, touch_path: str, abs_max: int):
        self._panel = panel_module
        self._path = touch_path
        self._abs_max = abs_max
        self._inverse = None  # (i11, i12, i21, i22, b1, b2)
        self._lock = threading.Lock()

    def _derive(self) -> None:
        panel = self._panel
        deadline = time.monotonic() + 5.0
        while panel.touch_device is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if panel.touch_device is None:
            raise RuntimeError("panel did not open the virtual touch device; "
                               "is TOUCH_DEVICE_PATH set?")
        m = self._abs_max
        f = panel._transform_touch_coordinates
        l0 = f(0, 0)
        l1 = f(m, 0)
        l2 = f(0, m)
        # L(raw) = A @ raw + b, columns of A from the probes.
        a11 = (l1[0] - l0[0]) / m
        a21 = (l1[1] - l0[1]) / m
        a12 = (l2[0] - l0[0]) / m
        a22 = (l2[1] - l0[1]) / m
        b1, b2 = float(l0[0]), float(l0[1])
        det = a11 * a22 - a12 * a21
        if abs(det) < 1e-9:
            raise RuntimeError("touch transform is degenerate (det ~ 0)")
        i11, i12 = a22 / det, -a12 / det
        i21, i22 = -a21 / det, a11 / det
        self._inverse = (i11, i12, i21, i22, b1, b2)

        # Self-check: forward(inverse(p)) within a few px (int-floor slack).
        max_err = 0.0
        for fx in (0.1, 0.5, 0.9):
            for fy in (0.1, 0.5, 0.9):
                lx = fx * (self._logical_dims()[0] - 1)
                ly = fy * (self._logical_dims()[1] - 1)
                rx, ry = self._to_raw(lx, ly)
                ox, oy = f(rx, ry)
                max_err = max(max_err, abs(ox - lx), abs(oy - ly))
        if max_err > 3.0:
            raise RuntimeError("touch inverse self-check failed (max err %.1f px)" % max_err)
        print("virtual: touch inverse derived (max round-trip error %.1f px)" % max_err,
              flush=True)

    def _logical_dims(self) -> Tuple[int, int]:
        return self._panel.WIDTH, self._panel.HEIGHT

    def _to_raw(self, lx: float, ly: float) -> Tuple[int, int]:
        i11, i12, i21, i22, b1, b2 = self._inverse
        dx, dy = lx - b1, ly - b2
        rx = i11 * dx + i12 * dy
        ry = i21 * dx + i22 * dy
        clamp = lambda v: max(0, min(self._abs_max, int(round(v))))
        return clamp(rx), clamp(ry)

    def tap(self, logical_x: float, logical_y: float) -> None:
        with self._lock:
            if self._inverse is None:
                self._derive()
        rx, ry = self._to_raw(logical_x, logical_y)
        fake_evdev = sys.modules["evdev"]
        fake_evdev.queue_tap_events(self._path, rx, ry)


# ---------------------------------------------------------------------------
# The virtual panel
# ---------------------------------------------------------------------------
class VirtualPanel:
    """Boot glue. Construct, then call import_panel() and run panel.main()
    on the main thread."""

    def __init__(self, env_file: Optional[str] = None,
                 extra_env: Optional[Dict[str, str]] = None):
        if extra_env:
            os.environ.update(extra_env)
        if env_file is None:
            for candidate in (os.path.join(REPO_ROOT, "virtual", "panel.env"),
                              os.path.join(REPO_ROOT, "virtual", "panel.env.example")):
                if os.path.exists(candidate):
                    env_file = candidate
                    break
        if env_file:
            load_env_file(env_file)
            print("virtual: environment loaded from %s" % env_file, flush=True)
        self.font_path, self.font_fallback = resolve_font()

        self.fb_width = int(os.environ.get("VIRTUAL_FB_WIDTH", "720"))
        self.fb_height = int(os.environ.get("VIRTUAL_FB_HEIGHT", "480"))
        self.fb_bpp = int(os.environ.get("VIRTUAL_FB_BPP", "32"))
        self.touch_path = os.environ.get("TOUCH_DEVICE_PATH") or "/dev/input/event0"
        os.environ.setdefault("TOUCH_DEVICE_PATH", self.touch_path)
        self.touch_abs_max = int(os.environ.get("VIRTUAL_TOUCH_ABS_MAX", "4095"))

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from virtual.shims.broker import MiniBroker
        from virtual.shims.install import install_shims
        self.broker = MiniBroker()
        self.frames = FrameStore()
        install_shims(self.broker, self.frames.on_frame,
                      self.fb_width, self.fb_height, self.fb_bpp,
                      self.touch_path, self.touch_abs_max)
        self.panel = None
        self.touch_injector: Optional[TouchInjector] = None

    def import_panel(self, panel_args: Optional[List[str]] = None):
        sys.argv = ["mqtt_fb_panel.py"] + list(panel_args or [])
        import mqtt_fb_panel  # noqa: E402  (fakes already installed)
        self.panel = mqtt_fb_panel
        self.touch_injector = TouchInjector(mqtt_fb_panel, self.touch_path,
                                            self.touch_abs_max)
        return mqtt_fb_panel

    # -- controls (safe from any thread) -------------------------------------

    def tap(self, x: float, y: float) -> None:
        self.touch_injector.tap(x, y)

    def inject_mqtt(self, topic: str, payload, retain: bool = False, qos: int = 0) -> None:
        self.broker.inject(topic, payload, qos=qos, retain=retain)

    def request_shutdown(self) -> None:
        """Ask the panel main loop to exit through its regular cleanup path
        with a clean (0) exit code — same flag the MQTT restart command sets,
        but without touching _exit_code (which defaults to 0)."""
        self.panel._shutdown_requested = True

    def state(self) -> Dict[str, Any]:
        panel = self.panel
        retained = self.broker.retained_snapshot()
        availability_topic = os.environ.get("MQTT_AVAILABILITY_TOPIC", "")
        mode_topic = os.environ.get("MQTT_MODE_TOPIC", "")
        client = getattr(panel, "mqtt_client", None) if panel else None
        lc = sys.modules.get("lcars_constants")
        client_id = os.environ.get("MQTT_CLIENT_ID", "")
        return {
            "mode": getattr(panel, "current_display_mode", None) if panel else None,
            "connected": bool(client.is_connected()) if client else False,
            "subscriptions": self.broker.subscription_count(client_id),
            "availability": retained.get(availability_topic),
            "mode_retained": retained.get(mode_topic),
            "retained": retained,
            "panel_publishes": self.broker.panel_publishes(),
            "frame_seq": self.frames.seq,
            "dims": {"w": self.fb_width, "h": self.fb_height,
                     "logical_w": getattr(panel, "WIDTH", None) if panel else None,
                     "logical_h": getattr(panel, "HEIGHT", None) if panel else None,
                     "rotate": getattr(lc, "ROTATE", None) if lc else None,
                     "bpp": self.fb_bpp},
            "font": {"path": self.font_path, "fallback": self.font_fallback,
                     "bar_height": getattr(lc, "BAR_HEIGHT", None) if lc else None},
            "prefixes": {
                "topic": os.environ.get("MQTT_TOPIC_PREFIX", ""),
                "control": os.environ.get("MQTT_CONTROL_TOPIC_PREFIX", ""),
                "availability": availability_topic,
                "mode": mode_topic,
            },
            "messages_in_store": len(panel.messages_store) if panel else 0,
        }

    def start_state_watcher(self, interval: float = 0.25) -> None:
        """Housekeeping thread: diff key state and emit SSE 'state' events."""
        def watch():
            last = None
            while True:
                try:
                    s = self.state()
                    key = (s["mode"], s["connected"], s["availability"],
                           s["mode_retained"], s["messages_in_store"])
                    if key != last:
                        last = key
                        self.frames.notify_state(s)
                except Exception as e:
                    print("virtual: state watcher error: %r" % e, flush=True)
                time.sleep(interval)
        threading.Thread(target=watch, name="virtual-state-watcher", daemon=True).start()
