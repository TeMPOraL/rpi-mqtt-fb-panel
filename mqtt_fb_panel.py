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
import os, sys, signal, textwrap, argparse, json
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw

# Project-specific modules
import lcars_constants as lc
from framebuffer_utils import fb, push, blank, WIDTH, HEIGHT
from lcars_drawing_utils import text_size # text_size is used for message rendering calculations
from lcars_ui_components import render_top_bar, render_bottom_bar


# ---------------------------------------------------------------------------
# Global Application Settings (from environment or defaults)
# ---------------------------------------------------------------------------
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "home/lcars_panel/")
LCARS_TITLE_TEXT = os.getenv("LCARS_TITLE_TEXT", "LCARS MQTT PANEL") # Currently not used directly in UI
MAX_MESSAGES_IN_STORE = 50 # Max number of messages to keep in the rolling display

# ---------------------------------------------------------------------------
# Message Rendering Logic
# ---------------------------------------------------------------------------
def render_messages():
    """Renders the LCARS UI and a rolling list of messages from messages_store."""
    img = Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR)
    draw = ImageDraw.Draw(img)

    # 1. Draw LCARS UI Chrome (Top and Bottom Bars)
    render_top_bar(draw, WIDTH)
    render_bottom_bar(draw, WIDTH, HEIGHT)

    # 2. Define Message Display Area & Columns (between top and bottom bars)
    # These calculations depend on constants from lc (lc.PADDING, lc.BAR_HEIGHT)
    message_area_y_start = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING
    message_area_y_end = HEIGHT - lc.PADDING - lc.BAR_HEIGHT - lc.PADDING
    message_area_height = message_area_y_end - message_area_y_start

    message_line_height = lc.BODY_FONT.size + 4  # Font size + padding between lines

    # Column definitions
    col_source_max_chars = 20
    # Estimate source col width based on M chars, or use a fraction of screen.
    # Using M chars is more font-robust.
    # text_size is now imported from lcars_drawing_utils
    source_char_w_tuple = text_size(draw, "M", lc.BODY_FONT)
    source_char_w = source_char_w_tuple[0] if source_char_w_tuple[0] > 0 else lc.BODY_FONT.size * 0.6

    col_source_width = int(min(WIDTH * 0.25, col_source_max_chars * source_char_w + lc.PADDING))

    col_time_text_example = "00:00:00"
    col_time_width = text_size(draw, col_time_text_example, lc.BODY_FONT)[0] + lc.PADDING # Includes its own right padding

    # Add extra lc.PADDING for left and right margins of the message list area
    message_area_horizontal_margin = lc.PADDING * 2

    col_source_x = message_area_horizontal_margin
    # Time column is right-aligned, so its x is not fixed but calculated per line for alignment

    col_message_x = col_source_x + col_source_width + lc.PADDING # lc.PADDING here is between source and message
    
    # Calculate message width:
    # Available space for message text is from col_message_x to
    # (WIDTH - message_area_horizontal_margin - col_time_width - lc.PADDING for msg/time padding)
    # Note: col_time_width already includes its own padding for the time text from the right edge.
    # The message area's right boundary for text is WIDTH - message_area_horizontal_margin.
    # The time column will take col_time_width from this right boundary.
    # The message text needs to end lc.PADDING before the time column conceptually starts.
    
    # Effective right boundary for message content before time column and its padding
    message_content_right_boundary = WIDTH - message_area_horizontal_margin - col_time_width 
                                     # (col_time_width includes padding for time text from edge)
                                     # No, col_time_width is just text_size + lc.PADDING.
                                     # The actual_time_x calculation handles alignment.

    # Let's recalculate col_message_width based on new margins:
    # Rightmost point for message text = (WIDTH - message_area_horizontal_margin) - col_time_width - lc.PADDING (padding between msg and time)
    # Start point for message text = col_message_x
    col_message_width = (WIDTH - message_area_horizontal_margin - col_time_width - lc.PADDING) - col_message_x


    # 3. Prepare and Render Messages
    processed_message_lines = []
    avg_char_width_message = source_char_w # Re-use for message wrapping estimation

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
        else: # Fallback if width is zero or negative
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
    lines_to_render_on_screen = []
    if message_line_height > 0 and message_area_height > 0:
        max_displayable_message_lines = message_area_height // message_line_height
        if max_displayable_message_lines > 0:
            lines_to_render_on_screen = processed_message_lines[-max_displayable_message_lines:]

    # Draw the messages
    current_render_y = message_area_y_start
    for line_data in lines_to_render_on_screen:
        # Ensure text fits vertically before drawing
        # Using BODY_FONT.size as an estimate of actual drawn height.
        if current_render_y + lc.BODY_FONT.size > message_area_y_end:
            break

        if line_data["source"]: # Draw source only if it's the first line of a message
            draw.text((col_source_x, current_render_y), line_data["source"], font=lc.BODY_FONT, fill=lc.TEXT_COLOR_BODY)

        draw.text((col_message_x, current_render_y), line_data["msg_part"], font=lc.BODY_FONT, fill=lc.TEXT_COLOR_BODY)

        if line_data["time"]: # Draw time only if it's the first line of a message
            time_w, _ = text_size(draw, line_data["time"], lc.BODY_FONT)
            # Align to far right edge of message area (screen minus new horizontal margin)
            actual_time_x = WIDTH - message_area_horizontal_margin - time_w 
            draw.text((actual_time_x, current_render_y), line_data["time"], font=lc.BODY_FONT, fill=lc.TEXT_COLOR_BODY)

        current_render_y += message_line_height

    push(img)

# ---------------------------------------------------------------------------
# Probe graphics
# ---------------------------------------------------------------------------

def probe(shape: str = "square", fill: bool = False):
    """Draw a 75 % square/ellipse centred on screen to test geometry."""
    img = Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR)
    draw = ImageDraw.Draw(img)

    size = int(min(WIDTH, HEIGHT) * 0.75)
    x0 = (WIDTH - size) // 2
    y0 = (HEIGHT - size) // 2
    x1 = x0 + size
    y1 = y0 + size

    if shape == "circle":
        if fill:
            draw.ellipse((x0, y0, x1, y1), fill=lc.PROBE_COLOUR)
        else:
            draw.ellipse((x0, y0, x1, y1), outline=lc.PROBE_COLOUR, width=4)
    else:  # square
        if fill:
            draw.rectangle((x0, y0, x1, y1), fill=lc.PROBE_COLOUR)
        else:
            draw.rectangle((x0, y0, x1, y1), outline=lc.PROBE_COLOUR, width=4)
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
