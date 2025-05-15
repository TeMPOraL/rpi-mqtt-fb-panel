import mmap, os, struct, fcntl, ctypes, array
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
        self.mem.close(); os.close(self.fd)


def open_fb(dev: str | None = None) -> FB:
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
    if lc.ROTATE:
        img = img.rotate(lc.ROTATE, expand=True)

    if fb.bpp == 16:  # RGB565 path
        rgb = np.asarray(img.convert("RGB"), dtype=np.uint16)
        r = (rgb[..., 0] >> 3) & 0x1F
        g = (rgb[..., 1] >> 2) & 0x3F
        b = (rgb[..., 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b
        fb.mem.seek(0)
        fb.mem.write(rgb565.astype('<u2').tobytes())
    else: # Fall‑back: XRGB8888 – assume little‑endian (most common for RPi framebuffers)
          # Or could be RGBA or BGRA depending on specific fb config.
          # Common for 32bpp on Pi is BGRA byte order for XRGB visual.
        bgra = np.asarray(img.convert("RGBA"), dtype=np.uint8) # Convert to RGBA
        # If framebuffer expects BGRA (typical for XRGB on little-endian):
        # Swap R and B channels: R is at index 0, G at 1, B at 2, A at 3
        # We want B G R A
        b = bgra[..., 2:3].copy()
        r = bgra[..., 0:1].copy()
        bgra[..., 0:1] = b # B to first channel
        bgra[..., 2:3] = r # R to third channel
        
        fb.mem.seek(0)
        fb.mem.write(bgra.tobytes())


def blank():
    """Clears the framebuffer to BG_COLOUR."""
    push(Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR))
