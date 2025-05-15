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
#
# LCARS colors via https://www.thelcars.com/colors.php
# Quick ref of colors used or considered to be used:
# - TNG orange - #FF8800 rgb(255, 136, 0)
# - TNG african-violet - #CC99FF (lavender) rgb(204, 153, 255)
# - TNG light yellow (buttons) - #ffcb5f rgb(255, 203, 95)
# - TNG orange (buttons) - #ff9d00 rgb(255, 157, 0)
# - TNG light blue (buttons) - #9ba2ff rgb(155, 162, 255)
# - TNG red (buttons) - #d47065 rgb(212, 112, 101)
# - TNG more saturated light yellow (buttons) - #ffcd5c rgb(255, 205, 92)
# - White (text highlight, red alert) - #FFFFFF rgb(255, 255, 255)
# - Black (button labels) - #000000 rgb(0, 0, 0)
# - Red (red alert primary) - #FF0000 rgb(255, 0, 0)
# ---------------------------------------------------------------------------
ROTATE       = int(os.getenv("DISPLAY_ROTATE", 0)) # 0 / 90 / 180 / 270
BG_COLOUR    = (0, 0, 0) # Black

# Core LCARS Colors (TNG/VOY inspired)
LCARS_ORANGE = (255, 157, 0)      # Main interactive elements, bars
LCARS_BLUE = (155, 162, 255)        # Secondary elements, some buttons
LCARS_YELLOW = (255, 203, 95)       # Accent elements, some buttons
LCARS_RED_DARK = (212, 112, 101)    # Warning/Alert buttons or accents
LCARS_BEIGE = (255, 204, 153)       # Often used for text or backgrounds in some schemes
LCARS_PURPLE_LIGHT = (204, 153, 255) # Body text, info messages

# Text Colors
TEXT_COLOR_TITLE = LCARS_ORANGE
TEXT_COLOR_BODY = LCARS_PURPLE_LIGHT
TEXT_COLOR_BUTTON_LABEL = (0, 0, 0) # Black
TEXT_COLOR_HIGHLIGHT = (255, 255, 255) # White

# Specific UI Element Colors (can be overridden by a theme later)
COLOR_BARS = LCARS_ORANGE
COLOR_BUTTON_CLEAR = LCARS_RED_DARK
COLOR_BUTTON_RELATIVE = LCARS_BLUE
COLOR_BUTTON_CLOCK = LCARS_YELLOW

PROBE_COLOUR = (255, 0, 255) # Magenta for probe

# NOTE: references a proper LCARS font that's (apparently) free for personal use.
# Not distributing it with this project. Alternatives include Antionio. Or just
# web-search for something if you don't have this one.
TITLE_FONT   = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf", 34)
BODY_FONT    = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf", 28)

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

# ---------------------------------------------------------------------------
# LCARS Drawing Helpers
# ---------------------------------------------------------------------------
def draw_lcars_shape(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, radius: int,
                     color_bg, left_round: bool = False, right_round: bool = False):
    """
    Draws an LCARS-style shape (rectangle with optional rounded ends).
    Radius is typically h // 2 for semi-circular ends.
    """
    if radius > min(w / 2, h / 2) and (left_round or right_round): # Avoid radius too large for shape
        radius = min(w // 2, h // 2)

    if left_round and right_round: # Pill shape
        draw.rectangle((x + radius, y, x + w - radius, y + h), fill=color_bg)
        draw.pieslice((x, y, x + 2 * radius, y + h), 90, 270, fill=color_bg)
        draw.pieslice((x + w - 2 * radius, y, x + w, y + h), -90, 90, fill=color_bg)
    elif left_round: # (] shape
        draw.rectangle((x + radius, y, x + w, y + h), fill=color_bg)
        draw.pieslice((x, y, x + 2 * radius, y + h), 90, 270, fill=color_bg)
    elif right_round: # [) shape
        draw.rectangle((x, y, x + w - radius, y + h), fill=color_bg)
        draw.pieslice((x + w - 2 * radius, y, x + w, y + h), -90, 90, fill=color_bg)
    else: # [] shape (rectangle)
        draw.rectangle((x, y, x + w, y + h), fill=color_bg)

def draw_text_in_rect(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
                      rect_x: int, rect_y: int, rect_w: int, rect_h: int,
                      text_color, align: str = "center", padding_x: int = 5):
    """Draws text within a given rectangle, with alignment."""
    text_w, text_h = text_size(draw, text, font=font)
    
    if align == "center":
        text_x_offset = (rect_w - text_w) // 2
    elif align == "left":
        text_x_offset = padding_x
    elif align == "right":
        text_x_offset = rect_w - text_w - padding_x
    else: # default to center
        text_x_offset = (rect_w - text_w) // 2

    # Ensure text doesn't overflow if rect is too small (basic clipping)
    if text_w > rect_w - 2 * padding_x and align != "center": # allow center to overflow if needed
        # Could implement truncation here if desired: text = text[:max_chars] + "..."
        pass # For now, let it draw, might be visually clipped by rect boundaries if text is too long

    text_x = rect_x + text_x_offset
    text_y = rect_y + (rect_h - text_h) // 2
    draw.text((text_x, text_y), text, font=font, fill=text_color)

# ---------------------------------------------------------------------------
# Framebuffer Blitting
# ---------------------------------------------------------------------------
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

    # LCARS UI Dimensions
    PADDING = 5  # General padding
    BAR_HEIGHT = TITLE_FONT.size + PADDING * 2 # Height of top and bottom bars
    CORNER_RADIUS = BAR_HEIGHT // 2
    BUTTON_PADDING_X = 10 # Horizontal padding inside buttons

    # --- 1. Draw Top Bar: (] [============================] EVENT LOG [) ---
    TOP_BAR_Y = PADDING
    # Left Terminator (])
    left_terminator_width = BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, PADDING, TOP_BAR_Y, left_terminator_width, BAR_HEIGHT, CORNER_RADIUS, COLOR_BARS, left_round=True)

    # Right Terminator [)
    right_terminator_width = BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, WIDTH - PADDING - right_terminator_width, TOP_BAR_Y, right_terminator_width, BAR_HEIGHT, CORNER_RADIUS, COLOR_BARS, right_round=True)
    
    # Central Bar Label "EVENT LOG"
    # Calculate width for the bar that holds "EVENT LOG"
    # It sits between the terminators, but "EVENT LOG" is to the right of a connecting bar segment
    event_log_text = "EVENT LOG"
    event_log_text_w, _ = text_size(draw, event_log_text, TITLE_FONT)
    
    # Connecting bar from left terminator to "EVENT LOG" area
    conn_bar_x_start = PADDING + left_terminator_width
    # Estimate some space for the "bar" part of "[============================]"
    # This is a bit of visual tuning. Let's say the label takes up its width + some padding.
    # The remaining space is split.
    total_bar_area_width = WIDTH - (2 * PADDING) - left_terminator_width - right_terminator_width
    
    # Position "EVENT LOG" text. For mockup: (] [long_bar] TEXT [)
    # The long_bar_width needs to be calculated.
    # Let's make the text element a fixed width or a portion of the central bar area.
    # For simplicity, let the text element be separate and placed.
    # The mockup implies: (] + Bar + Text_Element + [)
    # Let Text_Element be a rectangle.
    text_element_width = event_log_text_w + 4 * BUTTON_PADDING_X # Text width + generous padding
    text_element_x = WIDTH - PADDING - right_terminator_width - text_element_width

    # Main bar segment before the text element
    main_bar_width = text_element_x - conn_bar_x_start
    if main_bar_width > 0:
        draw_lcars_shape(draw, conn_bar_x_start, TOP_BAR_Y, main_bar_width, BAR_HEIGHT, 0, COLOR_BARS) # No rounding for this segment

    # "EVENT LOG" text element (as a non-rounded bar for its background)
    # This element itself is not rounded in the mockup, it's just text on the bar.
    # So, the main_bar_width should extend up to the right terminator, and text is drawn on it.
    # Revised logic for top bar: (] + Main_Bar_with_Text + [)
    main_bar_x = PADDING + left_terminator_width
    main_bar_w = WIDTH - (2 * PADDING) - left_terminator_width - right_terminator_width
    if main_bar_w > 0:
        draw_lcars_shape(draw, main_bar_x, TOP_BAR_Y, main_bar_w, BAR_HEIGHT, 0, COLOR_BARS) # Central bar
        draw_text_in_rect(draw, event_log_text, TITLE_FONT,
                          main_bar_x, TOP_BAR_Y, main_bar_w, BAR_HEIGHT,
                          TEXT_COLOR_TITLE, align="center", padding_x=BUTTON_PADDING_X)


    # --- 2. Draw Bottom Bar: (] MQTT STREAM [CLEAR] [RELATIVE] [CLOCK] [==) ---
    BOTTOM_BAR_Y = HEIGHT - PADDING - BAR_HEIGHT
    
    # Left Terminator (]) for bottom bar
    draw_lcars_shape(draw, PADDING, BOTTOM_BAR_Y, left_terminator_width, BAR_HEIGHT, CORNER_RADIUS, COLOR_BARS, left_round=True)

    # "MQTT STREAM" Label
    mqtt_stream_text = "MQTT STREAM"
    mqtt_stream_text_w, _ = text_size(draw, mqtt_stream_text, TITLE_FONT)
    mqtt_stream_label_x = PADDING + left_terminator_width + BUTTON_PADDING_X
    # Draw text directly on the bar, or give it a small bar segment
    # For now, draw text directly after left terminator
    # We need a bar segment for "MQTT STREAM"
    mqtt_stream_bar_w = mqtt_stream_text_w + 2 * BUTTON_PADDING_X
    draw_lcars_shape(draw, PADDING + left_terminator_width, BOTTOM_BAR_Y, mqtt_stream_bar_w, BAR_HEIGHT, 0, COLOR_BARS)
    draw_text_in_rect(draw, mqtt_stream_text, TITLE_FONT,
                      PADDING + left_terminator_width, BOTTOM_BAR_Y, mqtt_stream_bar_w, BAR_HEIGHT,
                      TEXT_COLOR_TITLE, align="center")

    current_x_bottom_bar = PADDING + left_terminator_width + mqtt_stream_bar_w + PADDING

    # Buttons: [CLEAR], [RELATIVE], [CLOCK]
    button_texts = ["CLEAR", "RELATIVE", "CLOCK"]
    button_colors = [COLOR_BUTTON_CLEAR, COLOR_BUTTON_RELATIVE, COLOR_BUTTON_CLOCK]
    
    for i, btn_text in enumerate(button_texts):
        btn_w, _ = text_size(draw, btn_text, BODY_FONT)
        button_total_width = btn_w + 2 * BUTTON_PADDING_X
        draw_lcars_shape(draw, current_x_bottom_bar, BOTTOM_BAR_Y, button_total_width, BAR_HEIGHT, 0, button_colors[i]) # Square buttons
        draw_text_in_rect(draw, btn_text, BODY_FONT,
                          current_x_bottom_bar, BOTTOM_BAR_Y, button_total_width, BAR_HEIGHT,
                          TEXT_COLOR_BUTTON_LABEL, align="center")
        current_x_bottom_bar += button_total_width + PADDING

    # Right Fill Bar [==)
    right_fill_bar_x = current_x_bottom_bar
    right_fill_bar_w = WIDTH - PADDING - right_fill_bar_x 
    if right_fill_bar_w > CORNER_RADIUS : # Ensure there's enough space for the rounded end
        draw_lcars_shape(draw, right_fill_bar_x, BOTTOM_BAR_Y, right_fill_bar_w, BAR_HEIGHT, CORNER_RADIUS, COLOR_BARS, right_round=True)
    elif right_fill_bar_w > 0: # If not enough for rounding, draw square
        draw_lcars_shape(draw, right_fill_bar_x, BOTTOM_BAR_Y, right_fill_bar_w, BAR_HEIGHT, 0, COLOR_BARS)


    # --- 3. Define Message Display Area & Columns ---
    message_area_y_start = TOP_BAR_Y + BAR_HEIGHT + PADDING
    message_area_y_end = BOTTOM_BAR_Y - PADDING
    message_area_height = message_area_y_end - message_area_y_start
    
    message_line_height = BODY_FONT.size + 4  # Font size + padding between lines
    
    # Column definitions
    col_source_max_chars = 20
    # Estimate source col width based on M chars, or use a fraction of screen.
    # Using M chars is more font-robust.
    source_char_w = text_size(draw, "M", BODY_FONT)[0] if text_size(draw, "M", BODY_FONT)[0] > 0 else BODY_FONT.size * 0.6
    col_source_width = int(min(WIDTH * 0.25, col_source_max_chars * source_char_w + PADDING))
    
    col_time_text_example = "00:00:00"
    col_time_width = text_size(draw, col_time_text_example, BODY_FONT)[0] + PADDING

    col_source_x = PADDING
    col_time_x = WIDTH - PADDING - col_time_width
    
    col_message_x = col_source_x + col_source_width + PADDING
    col_message_width = col_time_x - col_message_x - PADDING

    # --- 4. Prepare and Render Messages ---
    display_lines = [] # This will store tuples of (x, y, text, font, color) for drawing

    # Estimate avg char width for message wrapping.
    avg_char_width_message = source_char_w # Re-use, or calculate for typical chars

    current_render_y = message_area_y_start
    
    # Iterate a copy of messages_store, from oldest to newest for top-to-bottom display
    # but we want latest messages if list is too long, so process in reverse and take head.
    # Or, more simply, let deque handle maxlen and draw what fits from the end of deque.
    
    processed_message_lines = []

    for msg_obj in list(messages_store): # Iterate a copy
        try:
            timestamp_dt = datetime.fromisoformat(msg_obj["timestamp"].replace('Z', '+00:00'))
            ts_str = timestamp_dt.strftime("%H:%M:%S")
        except ValueError:
            ts_str = "??:??:??"

        source_text = msg_obj.get('source', 'N/A')
        if len(source_text) > col_source_max_chars:
            source_text = source_text[:col_source_max_chars-3] + "..."
        
        message_text_content = msg_obj.get('text', '')

        # Wrap message_text_content
        if avg_char_width_message > 0 and col_message_width > 0:
            chars_for_message_col = max(1, int(col_message_width / avg_char_width_message))
            wrapped_message_lines = textwrap.wrap(message_text_content, width=chars_for_message_col)
        else:
            wrapped_message_lines = [message_text_content] if message_text_content else [""]
        
        if not wrapped_message_lines and message_text_content: # textwrap might return empty for only spaces
             wrapped_message_lines = [message_text_content]
        elif not wrapped_message_lines: # Genuinely empty message
             wrapped_message_lines = [""]


        # First line of a message (source, first part of message, time)
        processed_message_lines.append({
            "source": source_text, "msg_part": wrapped_message_lines[0], "time": ts_str
        })
        # Subsequent lines of a wrapped message (only message part)
        for line_part in wrapped_message_lines[1:]:
            processed_message_lines.append({
                "source": "", "msg_part": line_part, "time": ""
            })

    # Calculate how many lines fit and get the latest ones
    if message_line_height > 0 and message_area_height > 0:
        max_displayable_message_lines = message_area_height // message_line_height
        lines_to_render_on_screen = processed_message_lines[-max_displayable_message_lines:]
    else:
        lines_to_render_on_screen = []
        
    # Draw the messages
    for line_data in lines_to_render_on_screen:
        if current_render_y + BODY_FONT.size > message_area_y_end: # Check if line fits
            break

        if line_data["source"]: # Draw source only if it's the first line of a message
            draw.text((col_source_x, current_render_y), line_data["source"], font=BODY_FONT, fill=TEXT_COLOR_BODY)
        
        draw.text((col_message_x, current_render_y), line_data["msg_part"], font=BODY_FONT, fill=TEXT_COLOR_BODY)
        
        if line_data["time"]: # Draw time only if it's the first line of a message
            # For right alignment of time:
            time_w, _ = text_size(draw, line_data["time"], BODY_FONT)
            actual_time_x = WIDTH - PADDING - time_w # Align to far right edge of screen minus padding
            draw.text((actual_time_x, current_render_y), line_data["time"], font=BODY_FONT, fill=TEXT_COLOR_BODY)
            
        current_render_y += message_line_height

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
