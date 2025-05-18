import mmap, os, struct, fcntl, ctypes, array
from typing import Optional
from dataclasses import dataclass
from PIL import Image
FBIO_WAITFORVSYNC = 0x4680   # ioctl id for vsync wait

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

    # --- build raw pixel buffer ------------------------------------------------
    if fb.bpp == 16:                       # RGB565
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = img.tobytes("raw", "BGR;16")
    else:                                  # 32-bpp XRGB/BGRA
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        buf = img.tobytes("raw", "BGRA")

    # --- wait for vertical blank to avoid tearing -----------------------------
    try:
        fcntl.ioctl(fb.fd, FBIO_WAITFORVSYNC, 0)
    except OSError:
        pass                               # Not all drivers support VSYNC ioctl

    # --- single fast memcpy into the mmap'ed framebuffer ----------------------
    fb.mem[:len(buf)] = buf                # ≈ memmove, much faster than .write()


def blank():
    """Clears the framebuffer to BG_COLOUR."""
    push(Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR))
