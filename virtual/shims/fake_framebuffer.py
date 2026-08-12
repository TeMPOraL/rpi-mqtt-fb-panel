"""Fake `framebuffer_utils`: same public surface, frames go to a sink.

Installed into sys.modules as 'framebuffer_utils' by install.py BEFORE any
panel module is imported, so the real module (which opens /dev/fb0 at import)
never runs. Interface and semantics mirror the real file line-for-line where
it matters:

- `fb` object with width/height/bpp/stride/mem/close(); close() marks mem
  unavailable and, like the real os.close(fd) on a stale fd, raises EBADF on
  a second call (the panel's _exit_in_progress latch avoids that today — the
  fake keeps the trap so future double-close bugs reproduce virtually).
- `push()` has the identical closed-fb guard, applies `lc.ROTATE` at call
  time via the same Image.rotate(expand=True), and for 16bpp applies the
  RGB565 quantization the real `tobytes("raw","BGR;16")` blit implies.
- `WIDTH`/`HEIGHT` use the identical pre-/post-rotation expression.

configure() must be called before the panel imports this module's names.
"""
import errno
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PIL import Image

import lcars_constants as lc  # requires repo root on sys.path + env already set
from virtual.shims import rgb565


class _Mem:
    """Stand-in for the mmap object: only `.closed` and `.close()` are used."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@dataclass
class FB:
    fd: int
    mem: Any
    width: int
    height: int
    bpp: int
    stride: int

    def close(self):
        # Mirror the real FB.close(): safe first close, EBADF on the second
        # (the real one calls os.close() on a stale fd).
        if self.mem and not self.mem.closed:
            self.mem.close()
        self.mem = None
        if self.fd:
            if getattr(self, "_fd_closed", False):
                raise OSError(errno.EBADF, "Bad file descriptor (virtual)")
            self._fd_closed = True


fb: Optional[FB] = None
WIDTH = 0
HEIGHT = 0
_frame_sink: Optional[Callable[[Image.Image], None]] = None


def configure(width: int, height: int, bpp: int,
              frame_sink: Callable[[Image.Image], None]) -> None:
    """Create the virtual framebuffer. Must run before panel imports."""
    global fb, WIDTH, HEIGHT, _frame_sink
    stride = (width * bpp + 7) // 8
    fb = FB(fd=99, mem=_Mem(), width=width, height=height, bpp=bpp, stride=stride)
    WIDTH, HEIGHT = (fb.width, fb.height) if lc.ROTATE in (0, 180) else (fb.height, fb.width)
    _frame_sink = frame_sink


def push(img: Image.Image):
    """Virtual blit: same guard/rotation/color pipeline as the device."""
    if fb is None or getattr(fb, "mem", None) is None or getattr(fb.mem, "closed", False):
        return
    if lc.ROTATE:
        img = img.rotate(lc.ROTATE, expand=True)

    if fb.bpp == 16:
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = rgb565.quantize(img)
    else:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        out = img

    if _frame_sink is not None:
        _frame_sink(out)


def blank():
    """Clears the framebuffer to BG_COLOUR."""
    push(Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR))
