"""RGB565 quantization mirroring framebuffer_utils' 16bpp branch semantics.

NOTE: the current device does NOT use this path. Investigation during harness
development showed that `img.tobytes("raw", "BGR;16")` from an RGB image has
no packer in ANY known Pillow version (8 through 12) — the panel's 16bpp
branch would raise ValueError — so the working device must be on the
32bpp/BGRA branch (RPi HDMI/composite framebuffers default to 32bpp). See
virtual/PLAN.md observations. This module is kept for a hypothetical 16bpp
display: it truncates each channel to 5/6/5 bits (with standard
bit-replication back to 8 for viewing) via per-channel `Image.point` LUTs,
which run in C — a per-pixel Python loop would take ~200ms per frame.
"""
from PIL import Image


def _expand5(v: int) -> int:
    """5-bit value (already in the top bits) expanded to 8 bits by replication."""
    v &= 0xF8
    return v | (v >> 5)


def _expand6(v: int) -> int:
    v &= 0xFC
    return v | (v >> 6)


# One flat 768-entry LUT: R, G, B channels concatenated (Image.point contract).
_LUT = [_expand5(i) for i in range(256)] + \
       [_expand6(i) for i in range(256)] + \
       [_expand5(i) for i in range(256)]


def quantize(img: Image.Image) -> Image.Image:
    """Return `img` with each channel quantized as the 16bpp framebuffer would."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img.point(_LUT)
