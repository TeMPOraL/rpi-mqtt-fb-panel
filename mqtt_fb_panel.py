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
import os, sys, signal, textwrap, argparse, json, socket
from collections import deque
from datetime import datetime
from dataclasses import dataclass
from typing import Optional # Optional will be used by the dataclass if we add optional fields later

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
HOSTNAME = socket.gethostname()
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "home/lcars_panel/")
MQTT_CONTROL_TOPIC_PREFIX = os.getenv("MQTT_CONTROL_TOPIC_PREFIX", f"lcars/{HOSTNAME}/").replace("<hostname>", HOSTNAME)
LOG_CONTROL_MESSAGES_STR = os.getenv("LOG_CONTROL_MESSAGES", "true").lower()
LOG_CONTROL_MESSAGES = LOG_CONTROL_MESSAGES_STR == "true"

LCARS_TITLE_TEXT = os.getenv("LCARS_TITLE_TEXT", "LCARS MQTT PANEL") # Currently not used directly in UI
MAX_MESSAGES_IN_STORE = int(os.getenv("MAX_MESSAGES_IN_STORE", "50")) # Max number of messages to keep
MESSAGE_AREA_HORIZONTAL_PADDING = lc.PADDING * 2 # Specific padding for the message list area

# Global application state
debug_layout_enabled = False
log_control_messages_enabled = LOG_CONTROL_MESSAGES # Initialized from env, can be changed by MQTT command

# ---------------------------------------------------------------------------
# Message Dataclass
# ---------------------------------------------------------------------------
@dataclass
class Message:
    text: str
    source: str
    importance: str
    timestamp: datetime # Store as datetime object
    topic: str

# ---------------------------------------------------------------------------
# Message Area Layout Calculation
# ---------------------------------------------------------------------------
def _calculate_message_area_layout(draw: ImageDraw.ImageDraw) -> dict:
    """Calculates dimensions and positions for the message display area and its columns."""
    layout = {}
    layout['message_area_y_start'] = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING
    layout['message_area_y_end'] = HEIGHT - lc.PADDING - lc.BAR_HEIGHT - lc.PADDING
    layout['message_area_height'] = layout['message_area_y_end'] - layout['message_area_y_start']
    layout['message_line_height'] = lc.BODY_FONT.size + 4  # Font size + padding between lines

    # Column definitions
    col_source_max_chars = 20
    # Estimate source col width based on M chars, or use a fraction of screen.
    source_char_w_tuple = text_size(draw, "M", lc.BODY_FONT)
    source_char_w = source_char_w_tuple[0] if source_char_w_tuple[0] > 0 else lc.BODY_FONT.size * 0.6
    layout['avg_char_width_message'] = source_char_w # Used for message wrapping

    layout['col_source_width'] = int(min(WIDTH * 0.25, col_source_max_chars * source_char_w + lc.PADDING))

    col_time_text_example = "00:00:00"
    layout['col_time_width'] = text_size(draw, col_time_text_example, lc.BODY_FONT)[0] + lc.PADDING

    layout['col_source_x'] = MESSAGE_AREA_HORIZONTAL_PADDING
    layout['col_message_x'] = layout['col_source_x'] + layout['col_source_width'] + lc.PADDING
    
    layout['col_message_width'] = (WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - layout['col_time_width'] - lc.PADDING) - layout['col_message_x']
    
    return layout

# ---------------------------------------------------------------------------
# Message Processing for Display
# ---------------------------------------------------------------------------
def _process_messages_for_display(draw: ImageDraw.ImageDraw, messages_to_process: list[Message], layout: dict) -> list[dict]:
    """Formats and wraps messages from the store into lines suitable for display."""
    processed_message_lines = []
    col_source_max_chars = 20 # Should ideally come from layout or be a constant

    for msg_obj in messages_to_process:
        ts_str = msg_obj.timestamp.strftime("%H:%M:%S")

        source_text = msg_obj.source
        if len(source_text) > col_source_max_chars:
            source_text = source_text[:col_source_max_chars-3] + "..."

        message_text_content = msg_obj.text

        if layout['avg_char_width_message'] > 0 and layout['col_message_width'] > 0:
            chars_for_message_col = max(1, int(layout['col_message_width'] / layout['avg_char_width_message']))
            wrapped_message_lines = textwrap.wrap(message_text_content, width=chars_for_message_col)
        else:
            wrapped_message_lines = [message_text_content] if message_text_content else [""]
        
        if not wrapped_message_lines and message_text_content:
             wrapped_message_lines = [message_text_content]
        elif not wrapped_message_lines:
             wrapped_message_lines = [""]

        processed_message_lines.append({
            "source": source_text, "msg_part": wrapped_message_lines[0], "time": ts_str
        })
        for line_part in wrapped_message_lines[1:]:
            processed_message_lines.append({
                "source": "", "msg_part": line_part, "time": ""
            })
    return processed_message_lines

# ---------------------------------------------------------------------------
# Main Rendering Function
# ---------------------------------------------------------------------------
def render_messages():
    """Renders the LCARS UI and a rolling list of messages."""
    img = Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR)
    draw = ImageDraw.Draw(img)

    # 1. Draw LCARS UI Chrome (Top and Bottom Bars)
    render_top_bar(draw, WIDTH, debug_layout_enabled)
    render_bottom_bar(draw, WIDTH, HEIGHT, debug_layout_enabled)

    # 2. Calculate Message Area Layout
    layout = _calculate_message_area_layout(draw)

    # Draw debug bounding boxes for message columns if enabled
    if debug_layout_enabled:
        # Source column
        draw.rectangle(
            (layout['col_source_x'], layout['message_area_y_start'],
             layout['col_source_x'] + layout['col_source_width'] -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )
        # Message column
        draw.rectangle(
            (layout['col_message_x'], layout['message_area_y_start'],
             layout['col_message_x'] + layout['col_message_width'] -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )
        # Time column
        time_col_x_start = WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - layout['col_time_width']
        draw.rectangle(
            (time_col_x_start, layout['message_area_y_start'],
             WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )

    # 3. Prepare Messages for Display
    # Create a copy for processing, as messages_store might be updated by MQTT thread
    current_messages_snapshot = list(messages_store) 
    processed_message_lines = _process_messages_for_display(draw, current_messages_snapshot, layout)

    # 4. Calculate how many lines fit and get the latest ones
    lines_to_render_on_screen = []
    if layout['message_line_height'] > 0 and layout['message_area_height'] > 0:
        max_displayable_message_lines = layout['message_area_height'] // layout['message_line_height']
        if max_displayable_message_lines > 0:
            lines_to_render_on_screen = processed_message_lines[-max_displayable_message_lines:]

    # 5. Draw the messages
    current_render_y = layout['message_area_y_start']
    for line_data in lines_to_render_on_screen:
        # Ensure text fits vertically before drawing
        if current_render_y + lc.BODY_FONT.size > layout['message_area_y_end']:
            break
        
        # Determine text color based on importance (though processed_message_lines doesn't store original importance)
        # For now, all messages rendered here use TEXT_COLOR_BODY or TEXT_COLOR_CONTROL if we adapt it.
        # This part needs the original message object or its importance to correctly color control messages.
        # Let's assume for now that _process_messages_for_display will pass through an 'importance' field.
        # This is a simplification; ideally, the original message object or its importance is available.
        # For now, we'll just use a placeholder. The `on_mqtt` part handles setting 'control' importance.
        # When rendering, we need to access that.
        # A quick fix: check source prefix for "LCARS/"
        text_fill_color = lc.TEXT_COLOR_BODY
        if line_data["source"].startswith("LCARS/"): # Crude check for control message
            text_fill_color = lc.TEXT_COLOR_CONTROL


        if line_data["source"]:
            draw.text((layout['col_source_x'], current_render_y), line_data["source"], font=lc.BODY_FONT, fill=text_fill_color)

        draw.text((layout['col_message_x'], current_render_y), line_data["msg_part"], font=lc.BODY_FONT, fill=text_fill_color)

        if line_data["time"]:
            time_w, _ = text_size(draw, line_data["time"], lc.BODY_FONT)
            # Align to far right edge of message area (screen minus MESSAGE_AREA_HORIZONTAL_PADDING)
            actual_time_x = WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - time_w
            draw.text((actual_time_x, current_render_y), line_data["time"], font=lc.BODY_FONT, fill=text_fill_color)

        current_render_y += layout['message_line_height']

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
    """Handles incoming MQTT messages, including control messages."""
    global debug_layout_enabled, log_control_messages_enabled
    try:
        payload_str = msg.payload.decode(errors="ignore").strip()
        print(f"Received message on topic {msg.topic}: '{payload_str}'", flush=True)

        # Check if it's a control message
        if msg.topic.startswith(MQTT_CONTROL_TOPIC_PREFIX):
            command_suffix = msg.topic[len(MQTT_CONTROL_TOPIC_PREFIX):]
            print(f"Control command: {command_suffix}, payload: '{payload_str}'", flush=True)

            needs_render = False
            if command_suffix == "debug-layout":
                if payload_str == "enable":
                    debug_layout_enabled = True
                    print("Layout debugging ENABLED", flush=True)
                elif payload_str == "disable" or payload_str == "":
                    debug_layout_enabled = False
                    print("Layout debugging DISABLED", flush=True)
                else:
                    print(f"Unknown payload for debug-layout: '{payload_str}'", flush=True)
                needs_render = True
            elif command_suffix == "log-control":
                if payload_str == "enable":
                    log_control_messages_enabled = True
                    print("Logging of control messages ENABLED", flush=True)
                elif payload_str == "disable" or payload_str == "":
                    log_control_messages_enabled = False
                    print("Logging of control messages DISABLED", flush=True)
                else:
                    print(f"Unknown payload for log-control: '{payload_str}'", flush=True)
                # No immediate render needed, only affects future messages
            else:
                print(f"Unknown control command suffix: {command_suffix}", flush=True)

            if log_control_messages_enabled:
                # Log the control command itself as a message if enabled
                control_msg_text = f"CMD: {command_suffix}"
                if payload_str: # Add payload to message if it exists
                    control_msg_text += f" PAYLOAD: {payload_str}"

                control_message_obj = Message(
                    text=control_msg_text,
                    source=f"LCARS/{command_suffix}",
                    importance="control", # Special importance for control messages
                    timestamp=datetime.now(),
                    topic=msg.topic
                )
                messages_store.append(control_message_obj)
                print(f"Stored control message: {control_message_obj}", flush=True)
                needs_render = True # Render if we logged it

            if needs_render:
                render_messages()
            return # Processed as control message

        # Regular message processing (JSON or raw)
        try:
            data = json.loads(payload_str)
            text_content = data.get("message")
            if not text_content:
                print("Error: Received JSON message is missing mandatory 'message' field.", flush=True)
                return

            source = data.get("source", "Unknown")
            importance = data.get("importance", "info")
            timestamp_str = data.get("timestamp")
        except json.JSONDecodeError:
            # If not JSON, treat the whole payload_str as the message text
            print(f"Warning: Could not decode JSON from topic {msg.topic}. Treating as raw text.", flush=True)
            text_content = payload_str
            source = "Raw Text"
            importance = "info"
            timestamp_str = None # No timestamp if raw

        timestamp_dt: datetime
        if timestamp_str:
            try:
                if timestamp_str.endswith('Z'):
                    timestamp_dt = datetime.fromisoformat(timestamp_str[:-1] + '+00:00')
                else:
                    timestamp_dt = datetime.fromisoformat(timestamp_str)
            except ValueError:
                print(f"Warning: Could not parse provided timestamp '{timestamp_str}'. Using current time.", flush=True)
                timestamp_dt = datetime.now()
        else:
            timestamp_dt = datetime.now()

        new_msg_obj = Message(
            text=text_content,
            source=source,
            importance=importance,
            timestamp=timestamp_dt,
            topic=msg.topic
        )
        messages_store.append(new_msg_obj)
        print(f"Stored new message: {new_msg_obj}", flush=True)
        render_messages()

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
        # Populate with sample messages for debug mode using the Message dataclass
        messages_store.append(Message(
            text="This is a debug message for the LCARS panel.",
            source="System", importance="info", timestamp=datetime.now(), topic="debug/system"
        ))
        messages_store.append(Message(
            text="Another short one.",
            source="Debug", importance="info", timestamp=datetime.now(), topic="debug/short"
        ))
        messages_store.append(Message(
            text="This is a slightly longer debug message that should demonstrate how text wrapping might work on the display, hopefully spanning multiple lines if necessary.",
            source="Debugger", importance="info", timestamp=datetime.now(), topic="debug/long"
        ))
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
    print(f"Subscribed to data topic: {subscription_topic}", flush=True)

    # Subscribe to control topic
    control_subscription_topic = f"{MQTT_CONTROL_TOPIC_PREFIX.rstrip('/')}/#"
    client.subscribe(control_subscription_topic)
    print(f"Subscribed to control topic: {control_subscription_topic}", flush=True)


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
