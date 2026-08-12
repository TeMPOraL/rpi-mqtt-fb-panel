"""Validate the RGB565 LUT against canonical 5/6/5 truncation + replication.

(It cannot be validated against Pillow's own "BGR;16" packer: no Pillow
version 8-12 provides an RGB source packer for it — which also means the
panel's 16bpp framebuffer branch is dead code; the device runs the 32bpp
path. See virtual/PLAN.md observations.)
"""
from PIL import Image

from virtual.shims.rgb565 import quantize


def _reference(r, g, b):
    r5 = r >> 3
    g6 = g >> 2
    b5 = b >> 3
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


def _gradient_image():
    img = Image.new("RGB", (256, 4))
    data = []
    data += [(i, 0, 0) for i in range(256)]
    data += [(0, i, 0) for i in range(256)]
    data += [(0, 0, i) for i in range(256)]
    data += [(i, 255 - i, (i * 7) % 256) for i in range(256)]
    img.putdata(data)
    return img


def test_lut_matches_reference_565():
    img = _gradient_image()
    expected = [_reference(*px) for px in img.getdata()]
    actual = list(quantize(img).getdata())
    assert actual == expected


def test_quantize_idempotent():
    img = _gradient_image()
    once = quantize(img)
    twice = quantize(once)
    assert list(once.getdata()) == list(twice.getdata())
