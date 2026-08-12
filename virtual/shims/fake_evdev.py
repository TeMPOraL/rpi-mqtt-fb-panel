"""Fake `evdev` module: a virtual touchscreen fed by injected tap events.

Installed into sys.modules as 'evdev' by install.py. Exports all four names
the panel imports atomically (`from evdev import InputDevice, categorize,
ecodes, list_devices`) plus AbsInfo/InputEvent for realism.

Shapes are python-evdev-faithful; in particular `capabilities()` returns
EV_ABS entries as (code, AbsInfo) tuples — `_transform_touch_coordinates`
relies on `dict(...)` over exactly that shape. (Side effect, documented in
virtual/PLAN.md: the panel's auto-detect can't match this shape, so
TOUCH_DEVICE_PATH must be set explicitly — true on real hardware as well.)
"""
import threading
import time
from collections import deque, namedtuple
from types import SimpleNamespace
from typing import Dict, List

# Real Linux input event codes (subset the panel uses).
ecodes = SimpleNamespace(
    EV_SYN=0,
    EV_KEY=1,
    EV_ABS=3,
    ABS_X=0,
    ABS_Y=1,
    BTN_TOUCH=330,
)

AbsInfo = namedtuple("AbsInfo", ["value", "min", "max", "fuzz", "flat", "resolution"])
InputEvent = namedtuple("InputEvent", ["sec", "usec", "type", "code", "value"])


class _Backing:
    """Shared state for a registered virtual device (one queue per path,
    shared by all InputDevice handles opened on it)."""

    def __init__(self, path: str, name: str, abs_max: int):
        self.path = path
        self.name = name
        self.abs_max = abs_max
        self.events: deque = deque()
        self.lock = threading.Lock()


_registry: Dict[str, _Backing] = {}

# Optional hook invoked at the top of every InputDevice.read_one() call — the
# panel's main loop polls read_one() every ~10ms, which makes this the natural
# heartbeat for single-threaded environments (Pyodide) to drain browser input
# and pump the inline MQTT client. Unused (None) under CPython.
poll_hook = None


def register_device(path: str = "/dev/input/event0",
                    name: str = "virtual-lcars-touchscreen",
                    abs_max: int = 4095) -> None:
    _registry[path] = _Backing(path, name, abs_max)


def list_devices() -> List[str]:
    return list(_registry)


def categorize(event) -> str:
    return "virtual input event %r" % (event,)


class InputDevice:
    def __init__(self, path: str):
        backing = _registry.get(path)
        if backing is None:
            raise FileNotFoundError(2, "No such virtual input device", path)
        self._backing = backing
        self.path = path
        self.name = backing.name

    def capabilities(self, verbose: bool = False, absinfo: bool = True):
        absinfo_x = AbsInfo(value=0, min=0, max=self._backing.abs_max,
                            fuzz=0, flat=0, resolution=0)
        absinfo_y = AbsInfo(value=0, min=0, max=self._backing.abs_max,
                            fuzz=0, flat=0, resolution=0)
        if verbose:
            # Only ever printed by the panel; shape approximates python-evdev.
            return {
                ("EV_KEY", ecodes.EV_KEY): [("BTN_TOUCH", ecodes.BTN_TOUCH)],
                ("EV_ABS", ecodes.EV_ABS): [
                    (("ABS_X", ecodes.ABS_X), absinfo_x),
                    (("ABS_Y", ecodes.ABS_Y), absinfo_y),
                ],
            }
        return {
            ecodes.EV_KEY: [ecodes.BTN_TOUCH],
            ecodes.EV_ABS: [(ecodes.ABS_X, absinfo_x), (ecodes.ABS_Y, absinfo_y)],
        }

    def read_one(self):
        if poll_hook is not None:
            poll_hook()
        with self._backing.lock:
            if self._backing.events:
                return self._backing.events.popleft()
        return None

    def close(self) -> None:
        return None


def queue_tap_events(path: str, raw_x: int, raw_y: int) -> None:
    """Enqueue the event sequence of one tap at raw device coordinates.

    The panel consumes ABS_X/ABS_Y then acts on BTN_TOUCH value==1; the
    release event is ignored by its `value == 1` check, as on real streams.
    """
    backing = _registry.get(path)
    if backing is None:
        raise KeyError("no virtual touch device registered at %s" % path)
    now = time.time()
    sec, usec = int(now), int((now % 1) * 1e6)
    seq = [
        InputEvent(sec, usec, ecodes.EV_ABS, ecodes.ABS_X, int(raw_x)),
        InputEvent(sec, usec, ecodes.EV_ABS, ecodes.ABS_Y, int(raw_y)),
        InputEvent(sec, usec, ecodes.EV_KEY, ecodes.BTN_TOUCH, 1),
        InputEvent(sec, usec, ecodes.EV_SYN, 0, 0),
        InputEvent(sec, usec, ecodes.EV_KEY, ecodes.BTN_TOUCH, 0),
        InputEvent(sec, usec, ecodes.EV_SYN, 0, 0),
    ]
    with backing.lock:
        backing.events.extend(seq)
