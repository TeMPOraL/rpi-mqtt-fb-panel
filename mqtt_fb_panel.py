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
LCARS_TITLE_TEXT = os.getenv("LCARS_TITLE_TEXT", "LCARS MQTT PANEL")
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


def render_messages():
    """Renders the fixed title and a rolling list of messages from messages_store."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR)
    draw = ImageDraw.Draw(img)

    # 1. Draw Fixed Title (top-right)
    title_padding = 10
    title_w, title_h = text_size(draw, LCARS_TITLE_TEXT, font=TITLE_FONT)
    title_x = WIDTH - title_w - title_padding
    title_y = title_padding
    draw.text((title_x, title_y), LCARS_TITLE_TEXT, font=TITLE_FONT, fill=TITLE_COLOUR)

    # 2. Define Message Area
    message_area_start_y = title_y + title_h + title_padding
    message_line_height = BODY_FONT.size + 4  # Font size + padding between lines
    left_padding = 10
    right_padding = 10

    # 3. Prepare lines from messages_store
    all_render_lines = []
    # Estimate avg char width for text wrapping. 'M' is a wide character.
    # If text_size returns (0,0) for a single char (older Pillow), use a fallback.
    avg_char_width_M = text_size(draw, "M", BODY_FONT)[0]
    if avg_char_width_M == 0: # Fallback if 'M' gives 0 width
        avg_char_width_M = BODY_FONT.size * 0.55 # Rough estimate
    
    for msg_obj in list(messages_store): # Iterate a copy
        try:
            # Format timestamp
            timestamp_dt = datetime.fromisoformat(msg_obj["timestamp"].replace('Z', '+00:00'))
            ts_str = timestamp_dt.strftime("%H:%M:%S")
        except ValueError:
            ts_str = "??:??:??" # Fallback for invalid timestamp

        prefix = f"[{ts_str}] [{msg_obj.get('source', 'N/A')}] "
        
        prefix_width = text_size(draw, prefix, BODY_FONT)[0]
        available_text_pixel_width = WIDTH - left_padding - prefix_width - right_padding
        
        # Calculate characters for textwrap based on available pixel width
        if avg_char_width_M > 0:
            chars_for_message = max(1, int(available_text_pixel_width / avg_char_width_M))
        else: # Should not happen with fallback, but as a safeguard
            chars_for_message = 20 

        message_text = msg_obj.get('text', '')
        wrapped_text_lines = textwrap.wrap(message_text, width=chars_for_message, subsequent_indent="  ") # Indent subsequent lines of same message

        if wrapped_text_lines:
            all_render_lines.append(prefix + wrapped_text_lines[0])
            for wrapped_line_part in wrapped_text_lines[1:]:
                # For subsequent lines of a single wrapped message, we add them with prefix spacing
                # The `subsequent_indent` in textwrap handles the visual indent *within* the wrapped part.
                # Here, we ensure the line starts aligned with the message text, not the timestamp.
                # This part might need refinement based on how textwrap.wrap + subsequent_indent behaves.
                # A simpler approach: add prefix only to the first line.
                all_render_lines.append(" " * text_size(draw, prefix, BODY_FONT)[0] // avg_char_width_M + wrapped_line_part) # Approximate spacing
        elif message_text: # Non-empty message but wrap returned empty (e.g. only spaces)
             all_render_lines.append(prefix + message_text)
        else: # Empty message
            all_render_lines.append(prefix)


    # 4. Calculate how many lines fit and get the latest ones
    if message_line_height > 0:
        max_displayable_message_lines = (HEIGHT - message_area_start_y) // message_line_height
    else:
        max_displayable_message_lines = 0
        
    lines_to_display = all_render_lines[-max_displayable_message_lines:]

    # 5. Draw the messages
    current_y = message_area_start_y
    for line_text in lines_to_display:
        draw.text((left_padding, current_y), line_text, font=BODY_FONT, fill=BODY_COLOUR)
        current_y += message_line_height
        if current_y > HEIGHT: # Stop if we run out of screen
            break
            
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
        print(f"Received message on topic {msg.topic}: {payload_str}", flush=True)
        data = json.loads(payload_str)

        text_content = data.get("message")
        if not text_content:
            print("Error: Received JSON message is missing mandatory 'message' field.", flush=True)
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
        print(f"Stored new message: {new_message}", flush=True)
        # print(f"Current messages_store: {list(messages_store)}", flush=True) # Uncomment for debugging

        render_messages() # Trigger re-render with new message

    except json.JSONDecodeError:
        print(f"Warning: Could not decode JSON from topic {msg.topic}. Treating as raw text: {payload_str}", flush=True)
        new_message = {
            "text": payload_str,
            "source": "Raw Text",
            "importance": "info", # Or a new category like "raw_text"
            "timestamp": datetime.now().isoformat(),
            "topic": msg.topic
        }
        messages_store.append(new_message)
        print(f"Stored raw text message: {new_message}", flush=True)
        render_messages() # Trigger re-render with new raw message
    except Exception as e:
        print(f"A critical error occurred in on_mqtt processing message from topic {msg.topic}: {e}", flush=True)


def main():
    print("Welcome to LCARS MQTT Alert Panel", flush=True)
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
        # Populate with sample messages for debug mode
        messages_store.append({
            "text": "This is a debug message for the LCARS panel.",
            "source": "System", "importance": "info", "timestamp": datetime.now().isoformat()
        })
        messages_store.append({
            "text": "Another short one.",
            "source": "Debug", "importance": "info", "timestamp": datetime.now().isoformat()
        })
        messages_store.append({
            "text": "This is a slightly longer debug message that should demonstrate how text wrapping might work on the display, hopefully spanning multiple lines if necessary.",
            "source": "Debugger", "importance": "info", "timestamp": datetime.now().isoformat()
        })
        render_messages()
        fb.close(); sys.exit(0)

    # For MQTTv5, providing an empty client_id and setting protocol=mqtt.MQTTv5
    # should result in a non-persistent session (clean start).
    # The `clean_session` parameter is not used for MQTTv5 and causes an error.
    client = mqtt.Client(client_id="", protocol=mqtt.MQTTv5)
    # If using paho-mqtt v2.x, one might use:
    # client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="", protocol=mqtt.MQTTv5)
    # and then set client.connect(..., clean_start=True, ...)
    
    client.on_message = on_mqtt
    client.username_pw_set(os.getenv("MQTT_USER", "alertpanel"), os.getenv("MQTT_PASS", "secretpassword"))

    try:
        print(f"Attempting to connect to MQTT broker: {os.getenv('MQTT_HOST', 'example-host.local')}:{os.getenv('MQTT_PORT', 1883)}", flush=True)
        client.connect(os.getenv("MQTT_HOST", "example-host.local"),
                       int(os.getenv("MQTT_PORT", 1883)))
    except Exception as e:
        print(f"Fatal error: Could not connect to MQTT broker: {e}", flush=True)
        fb.close()
        sys.exit(1) # Exit with an error code

    subscription_topic = f"{MQTT_TOPIC_PREFIX.rstrip('/')}/#"
    client.subscribe(subscription_topic)
    print(f"Subscribed to: {subscription_topic}", flush=True)

    def bye(*_):
        blank() # Clear screen on exit
        fb.close(); sys.exit(0)
    signal.signal(signal.SIGINT, bye); signal.signal(signal.SIGTERM, bye)

    print("client ready to loop", flush=True)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("Exiting due to KeyboardInterrupt...", flush=True)
    except Exception as e:
        print(f"Critical error in MQTT loop: {e}", flush=True)
    finally:
        print("MQTT loop_forever has exited.", flush=True)
        # client.disconnect() # Ensure client is disconnected if not already
        # bye() # Call the cleanup handler if loop_forever exits for any reason other than SIGINT/SIGTERM

    print("Script main function finished.", flush=True)

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
