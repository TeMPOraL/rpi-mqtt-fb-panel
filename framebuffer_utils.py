import mmap, os, struct, fcntl, ctypes, array
from typing import Optional
from dataclasses import dataclass
import numpy as np
from PIL import Image

import lcars_constants as lc

# ---------------------------------------------------------------------------
# Framebuffer access helpers
# ---------------------------------------------------------------------------
FBIOGET_VSCREENINFO = 0x4600  # struct fb_var_screeninfo

@dataclass
class FB:
    fd: int
    mem: mmap.mmap
    width: int
    height: int
    bpp: int
    stride: int

    def close(self):
        # Close safely and mark as unavailable so later calls can detect it.
        if self.mem and not self.mem.closed:
            self.mem.close()
        self.mem = None
        if self.fd:
            os.close(self.fd)


def open_fb(dev: Optional[str] = None) -> FB:
    """Open the framebuffer (env FBDEV overrides *dev*). Works on 32‑bit Pi."""
    dev = os.getenv("FBDEV", dev or "/dev/fb0")
    fd = os.open(dev, os.O_RDWR | os.O_SYNC)

    # Read basic geometry
    vs = array.array('I', [0] * 40)              # enough for struct fb_var_screeninfo
    fcntl.ioctl(fd, FBIOGET_VSCREENINFO, vs, True)
    xres, yres, bpp = vs[0], vs[1], vs[6]

    stride = (xres * bpp + 7) // 8               # bytes per line (safe on 32‑bit)
    size   = stride * yres                       # mmap len ≤ a few MB
    mem = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
    return FB(fd, mem, xres, yres, bpp, stride)

# ---------------------------------------------------------------------------
# Framebuffer object and derived dimensions
# ---------------------------------------------------------------------------
fb = open_fb()
WIDTH, HEIGHT = (fb.width, fb.height) if lc.ROTATE in (0, 180) else (fb.height, fb.width)

# ---------------------------------------------------------------------------
# Framebuffer Blitting
# ---------------------------------------------------------------------------
def push(img: Image.Image):
    """Convert PIL image to native RGB565/XRGB8888 and blit to the framebuffer."""
    # Skip drawing if the framebuffer is already closed (e.g. second shutdown call)
    if fb is None or getattr(fb, "mem", None) is None or getattr(fb.mem, "closed", False):
        return
    if lc.ROTATE:
        img = img.rotate(lc.ROTATE, expand=True)

    if fb.bpp == 16:  # RGB565 fast path
        if img.mode != "RGB":
            img = img.convert("RGB")
        fb.mem.seek(0)
        fb.mem.write(img.tobytes("raw", "BGR;16"))  # Pillow does RGB→RGB565 in C
    else:  # 32-bpp
        # Pillow versions shipped with Raspberry-Pi OS cannot convert RGB→BGRA
        # directly.  Convert to RGBA first, then request raw bytes in BGRA order.
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        fb.mem.seek(0)
        fb.mem.write(img.tobytes("raw", "BGRA"))


def blank():
    """Clears the framebuffer to BG_COLOUR."""
    push(Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR))
