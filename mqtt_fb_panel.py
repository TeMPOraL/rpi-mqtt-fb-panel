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
import os, sys, signal, textwrap, argparse, json, socket, time
from collections import deque
from datetime import datetime, timezone
import zoneinfo # For timezone name
try:
    import tzlocal # For local timezone name
except ImportError:
    tzlocal = None

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, List


import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont

# Project-specific modules
import lcars_constants as lc
from framebuffer_utils import fb, push, blank, WIDTH, HEIGHT
from lcars_ui_components import render_top_bar, render_bottom_bar
from event_log_mode import render_event_log_full_panel
from clock_mode import render_clock_full_panel


# ---------------------------------------------------------------------------
# Global Application Settings (from environment or defaults)
# ---------------------------------------------------------------------------
HOSTNAME = socket.gethostname()
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "home/lcars_panel/")
MQTT_CONTROL_TOPIC_PREFIX = os.getenv("MQTT_CONTROL_TOPIC_PREFIX", f"lcars/{HOSTNAME}/").replace("<hostname>", HOSTNAME)
LOG_CONTROL_MESSAGES_STR = os.getenv("LOG_CONTROL_MESSAGES", "true").lower()
LOG_CONTROL_MESSAGES = LOG_CONTROL_MESSAGES_STR == "true"

MAX_MESSAGES_IN_STORE = int(os.getenv("MAX_MESSAGES_IN_STORE", "50")) # Max number of messages to keep
MESSAGE_AREA_HORIZONTAL_PADDING = lc.PADDING * 2 # Specific padding for the message list area

# Global application state
debug_layout_enabled = False
log_control_messages_enabled = LOG_CONTROL_MESSAGES # Initialized from env, can be changed by MQTT command
current_display_mode = "events" # "events" or "clock"

# Guard that prevents duplicate execution of the shutdown routine.
_exit_in_progress = False

# ---------------------------------------------------------------------------
# Message Dataclass
# ---------------------------------------------------------------------------
@dataclass
class Message:
    text: str
    source: str
    importance: str
    timestamp: datetime
    topic: str

# ---------------------------------------------------------------------------
# Main Rendering Dispatcher
# ---------------------------------------------------------------------------
def refresh_display():
    img = Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR)
    draw = ImageDraw.Draw(img)

    if current_display_mode == "events":
        render_event_log_full_panel(img, draw, messages_store, debug_layout_enabled)
    elif current_display_mode == "clock":
        render_clock_full_panel(img, draw, debug_layout_enabled)
    else:
        print(f"Error: Unknown display mode '{current_display_mode}'. Defaulting to Event Log.", flush=True)
        render_event_log_full_panel(img, draw, messages_store, debug_layout_enabled)

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

def on_mqtt(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Handles incoming MQTT messages, including control messages."""
    global debug_layout_enabled, log_control_messages_enabled, current_display_mode
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
                # No immediate render needed for this command itself, only affects future messages
            elif command_suffix == "mode-select":
                if payload_str == "events":
                    if current_display_mode != "events":
                        current_display_mode = "events"
                        print("Display mode switched to EVENTS", flush=True)
                        needs_render = True
                elif payload_str == "clock":
                    if current_display_mode != "clock":
                        current_display_mode = "clock"
                        print("Display mode switched to CLOCK", flush=True)
                        needs_render = True
                else:
                    print(f"Unknown payload for mode-select: '{payload_str}'", flush=True)
            else:
                print(f"Unknown control command suffix: {command_suffix}", flush=True)

            # Log the control command itself as a message if enabled
            if log_control_messages_enabled:
                control_message_obj = Message(
                    text=payload_str, 
                    source=f"LCARS/{command_suffix}",
                    importance="control",
                    timestamp=datetime.now(),
                    topic=msg.topic
                )
                messages_store.append(control_message_obj)
                print(f"Stored control message: {control_message_obj}", flush=True)
                # If mode is events, this message will be shown, so render.
                # If mode is clock, this message is stored but not shown immediately,
                # but the mode switch itself (if it happened) needs a render.
                if current_display_mode == "events": # Render if in events mode to show the logged control msg
                    needs_render = True
            
            if needs_render: # This will be true if debug-layout changed, or mode changed, or if in events mode and control msg logged
                refresh_display()
            return # Processed as control message

        # Regular message processing (JSON or raw) for event log
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
            
            # Determine source from topic suffix for raw text messages
            source_val = "Unknown" # Default
            if msg.topic.startswith(MQTT_TOPIC_PREFIX):
                suffix = msg.topic[len(MQTT_TOPIC_PREFIX):]
                if suffix:
                    source_val = suffix
                else: # Message topic is identical to MQTT_TOPIC_PREFIX
                    prefix_no_trailing_slash = MQTT_TOPIC_PREFIX.rstrip('/')
                    if not prefix_no_trailing_slash: # Prefix was just "/"
                        source_val = "/"
                    else:
                        source_val = prefix_no_trailing_slash.split('/')[-1]
            else:
                # Fallback if topic somehow doesn't start with the known prefix (should be rare for non-control messages)
                topic_parts = msg.topic.split('/')
                # Get last non-empty part of the topic
                last_part = topic_parts[-1] if topic_parts[-1] else (topic_parts[-2] if len(topic_parts) > 1 and topic_parts[-2] else msg.topic)
                source_val = last_part if last_part else "Unknown"

            source = source_val
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
        
        # Only re-render if in events mode.
        # Sticky messages might change this later.
        if current_display_mode == "events":
            refresh_display()

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
        refresh_display() # Use new dispatcher
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

    # Initial display render after setup
    refresh_display()

    # Initial display render after setup
    refresh_display()

    client.loop_start() # Start non-blocking loop
    print("MQTT client loop started in background.", flush=True)

    def bye(*_):
        # Ensure this logic runs only once; further calls just finish the exit.
        global _exit_in_progress
        if _exit_in_progress:
            sys.exit(0)
        _exit_in_progress = True

        print("Exiting...", flush=True)
        client.loop_stop()                     # Stop MQTT network thread
        blank()                                # Clear screen (safe if FB already closed)
        fb.close()                             # Release framebuffer resources
        sys.exit(0)
    signal.signal(signal.SIGINT, bye)
    signal.signal(signal.SIGTERM, bye)

    print("Main loop starting. Press Ctrl+C to exit.", flush=True)
    try:
        while True:
            if current_display_mode == "clock":
                refresh_display()
                
                # Calculate dynamic sleep to align with the next second
                now = datetime.now()
                # Calculate delay until the very start of the next second.
                # now.microsecond is in [0, 999999].
                # (1_000_000 - now.microsecond) is in [1, 1_000_000] microseconds.
                # sleep_for_alignment will be in (0.0, 1.0] seconds.
                sleep_for_alignment = (1_000_000 - now.microsecond) / 1_000_000.0
                
                # Ensure a minimum sleep duration (e.g., 10ms) to yield CPU,
                # even if the calculated alignment delay is extremely tiny.
                # If sleep_for_alignment is 0.000001s, we'll sleep 0.01s.
                # If sleep_for_alignment is 0.5s, we'll sleep 0.5s.
                actual_sleep_time = max(0.01, sleep_for_alignment)
                time.sleep(actual_sleep_time)
            else:
                # For non-clock modes, a longer, less frequent check is fine.
                # This prevents the loop from busy-waiting if no MQTT messages arrive.
                time.sleep(0.5) # Check for mode changes or other events periodically
            
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught in main loop.", flush=True)
    except Exception as e:
        print(f"Critical error in main loop: {e}", flush=True)
    finally:
        bye()

    print("Script main function finished.", flush=True)

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
