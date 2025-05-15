#!/usr/bin/env python3
"""
Framebuffer MQTT Alert Panel – v2.2
===================================
Fixes for Pi‑TFT quirks
----------------------
* Works on 32‑bit Raspberry Pi OS – no more mmap OverflowError.
* Calculates the stride from *xres × bpp* instead of mis‑parsing
  `fb_fix_screeninfo` (wrong index caused bogus >2 GB value).
* Still zero external C builds – only Pillow, NumPy, paho‑mqtt from apt.

One‑liner install:
    sudo apt install python3-paho-mqtt python3-pil python3-numpy fonts-dejavu-core

Run a test splash:
    FBDEV=/dev/fb0 python3 mqtt_fb_panel.py --debug

To move the console off the TFT (if it still appears):
    sudo sed -i 's/fbcon=map:[0-9]/fbcon=map:1/' /boot/cmdline.txt && sudo reboot

————————————————————————————————————————————————————————
"""
from __future__ import annotations
import mmap, os, struct, fcntl, sys, signal, textwrap, ctypes, array, argparse, json
from pathlib import Path
from dataclasses import dataclass
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont
import numpy as np

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
# Rendering constants (tweak to taste)
# ---------------------------------------------------------------------------
ROTATE       = 0                # 0 / 90 / 180 / 270
BG_COLOUR    = (0, 0, 0)
TITLE_COLOUR = (174, 174, 221)
BODY_COLOUR  = (255, 255, 255)
PROBE_COLOUR = (255, 0, 255)
TITLE_FONT   = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
BODY_FONT    = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)

MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "home/lcars_panel/")
MAX_MESSAGES_IN_STORE = 50 # Max number of messages to keep in the rolling display

# ---------------------------------------------------------------------------
# Framebuffer object and helpers
# ---------------------------------------------------------------------------
fb = open_fb()
WIDTH, HEIGHT = (fb.width, fb.height) if ROTATE in (0, 180) else (fb.height, fb.width)

print(WIDTH)
print(HEIGHT)
# ---------------------------------------------------------------------------
# Pillow helpers compatible with >=10 & <10
# ---------------------------------------------------------------------------

def text_size(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.ImageFont):
    """Return (w,h) for *txt* regardless of Pillow version."""
    if hasattr(draw, "textbbox"):
        x0,y0,x1,y1 = draw.textbbox((0,0), txt, font=font)
        return x1-x0, y1-y0
    return draw.textsize(txt, font=font)  # Pillow<10


def push(img: Image.Image):
    """Convert PIL image to native RGB565 and blit to the framebuffer."""
    if ROTATE:
        img = img.rotate(ROTATE, expand=True)

    if fb.bpp == 16:  # RGB565 path
        rgb = np.asarray(img.convert("RGB"), dtype=np.uint16)
        r = (rgb[..., 0] >> 3) & 0x1F
        g = (rgb[..., 1] >> 2) & 0x3F
        b = (rgb[..., 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b
        fb.mem.seek(0)
        fb.mem.write(rgb565.astype('<u2').tobytes())
    else:
        # Fall‑back: XRGB8888 – assume little‑endian
        argb = np.asarray(img.convert("RGB"), dtype=np.uint8)
        a = np.full_like(argb[..., 0:1], 255)
        bgra = np.dstack((argb[..., 2:3], argb[..., 1:2], argb[..., 0:1], a))
        fb.mem.seek(0); fb.mem.write(bgra.tobytes())


def blank():
    push(Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR))


def render(title: str, body: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR)
    draw = ImageDraw.Draw(img)

    # Title
    tw, th = text_size(draw, title, font=TITLE_FONT)
    draw.text(((WIDTH - tw) // 2, 10), title, font=TITLE_FONT, fill=TITLE_COLOUR)

    # Body wrapping
    max_chars = max(1, int(WIDTH / (BODY_FONT.size * 0.55)))
    y = th + 20
    for para in body.split("\n"):
        for line in textwrap.wrap(para, width=max_chars):
            draw.text((10, y), line, font=BODY_FONT, fill=BODY_COLOUR)
            y += BODY_FONT.size + 4
    push(img)

# ---------------------------------------------------------------------------
# Probe graphics
# ---------------------------------------------------------------------------

def probe(shape: str = "square", fill: bool = False):
    """Draw a 75 % square/ellipse centred on screen to test geometry."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR)
    draw = ImageDraw.Draw(img)

    size = int(min(WIDTH, HEIGHT) * 0.75)
    x0 = (WIDTH - size) // 2
    y0 = (HEIGHT - size) // 2
    x1 = x0 + size
    y1 = y0 + size

    if shape == "circle":
        if fill:
            draw.ellipse((x0, y0, x1, y1), fill=PROBE_COLOUR)
        else:
            draw.ellipse((x0, y0, x1, y1), outline=PROBE_COLOUR, width=4)
    else:  # square
        if fill:
            draw.rectangle((x0, y0, x1, y1), fill=PROBE_COLOUR)
        else:
            draw.rectangle((x0, y0, x1, y1), outline=PROBE_COLOUR, width=4)
    push(img)

# ---------------------------------------------------------------------------
# MQTT machinery
# ---------------------------------------------------------------------------
messages_store = deque(maxlen=MAX_MESSAGES_IN_STORE)

def on_mqtt(client, userdata, msg):
    """Handles incoming MQTT messages."""
    try:
        payload_str = msg.payload.decode(errors="ignore")
        print(f"Received message on topic {msg.topic}: {payload_str}")
        data = json.loads(payload_str)

        text_content = data.get("message")
        if not text_content:
            print("Error: Received JSON message is missing mandatory 'message' field.")
            return

        source = data.get("source", "Unknown")
        importance = data.get("importance", "info")
        # Use provided timestamp or default to current time in ISO format
        timestamp_str = data.get("timestamp", datetime.now().isoformat())

        new_message = {
            "text": text_content,
            "source": source,
            "importance": importance,
            "timestamp": timestamp_str,
            "topic": msg.topic # Store the original topic for potential future use
        }
        messages_store.append(new_message)
        print(f"Stored new message: {new_message}")
        # print(f"Current messages_store: {list(messages_store)}") # Uncomment for debugging

        # Rendering will be handled in Phase 2. For now, we just store.
        # The old render call is removed as it's incompatible with the new message structure.
        # render(current["title"], current["body"]) # OLD RENDER CALL

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from topic {msg.topic}: {payload_str}")
    except Exception as e:
        print(f"An unexpected error occurred in on_mqtt: {e}")


def main():
    print("Welcome to LCARS MQTT Alert Panel")
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                        help="show sample content then quit")
    parser.add_argument("--probe", choices=["square", "circle"], help="draw shape then exit")
    parser.add_argument("--fill", action="store_true", help="fill probe shape (default outline)")
    args = parser.parse_args()

    blank()
    if args.probe:
        probe(args.probe, args.fill)
        fb.close(); sys.exit(0)
    if args.debug:
        render("MQTT Panel", "This is only a\nDEBUG splash.")
        fb.close(); sys.exit(0)

    client = mqtt.Client(protocol=mqtt.MQTTv5)
    client.on_message = on_mqtt
    client.username_pw_set(os.getenv("MQTT_USER", "alertpanel"), os.getenv("MQTT_PASS", "secretpassword"))
    client.connect(os.getenv("MQTT_HOST", "example-host.local"),
                   int(os.getenv("MQTT_PORT", 1883)))

    subscription_topic = f"{MQTT_TOPIC_PREFIX.rstrip('/')}/#"
    client.subscribe(subscription_topic)
    print(f"Subscribed to: {subscription_topic}")

    def bye(*_):
        blank() # Clear screen on exit
        fb.close(); sys.exit(0)
    signal.signal(signal.SIGINT, bye); signal.signal(signal.SIGTERM, bye)

    print("client ready to loop")

    client.loop_forever()

    print("client done")

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
