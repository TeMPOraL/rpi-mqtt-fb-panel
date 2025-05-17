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

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
except ImportError:
    print("Warning: python-evdev library not found. Touch input will be disabled.", flush=True)
    InputDevice = None
    categorize = None
    ecodes = None
    list_devices = None


# Project-specific modules
import lcars_constants as lc
from framebuffer_utils import fb, push, blank, WIDTH, HEIGHT # fb object needed for screen dimensions
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
TOUCH_DEVICE_PATH = os.getenv("TOUCH_DEVICE_PATH") # e.g., /dev/input/event0

MAX_MESSAGES_IN_STORE = int(os.getenv("MAX_MESSAGES_IN_STORE", "50")) # Max number of messages to keep
MESSAGE_AREA_HORIZONTAL_PADDING = lc.PADDING * 2 # Specific padding for the message list area

debug_layout_enabled = False
debug_touch_enabled = False # New state for touch debugging
last_debug_touch_coords: Optional[Tuple[int, int]] = None # Stores last touch for debug drawing
log_control_messages_enabled = LOG_CONTROL_MESSAGES # Initialized from env, can be changed by MQTT command
current_display_mode = "events" # "events" or "clock"
active_buttons: List[Dict[str, Any]] = [] # Stores {'id': str, 'rect': (x1,y1,x2,y2)}

# Touch input handling
touch_device: Optional[InputDevice] = None
last_touch_x: Optional[int] = None
last_touch_y: Optional[int] = None

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
    active_buttons.clear() # Clear buttons before redrawing UI

    if current_display_mode == "events":
        render_event_log_full_panel(img, draw, messages_store, active_buttons, debug_layout_enabled)
    elif current_display_mode == "clock":
        render_clock_full_panel(img, draw, active_buttons, debug_layout_enabled)
    else:
        print(f"Error: Unknown display mode '{current_display_mode}'. Defaulting to Event Log.", flush=True)
        render_event_log_full_panel(img, draw, messages_store, active_buttons, debug_layout_enabled)

    # --- Add touch debug visuals ---
    if debug_touch_enabled:
        if last_debug_touch_coords:
            lx, ly = last_debug_touch_coords
            radius = 20
            # Draw circle
            draw.ellipse(
                (lx - radius, ly - radius, lx + radius, ly + radius),
                outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, # Green
                width=2
            )
            # Draw crosshairs
            draw.line([(lx, 0), (lx, HEIGHT - 1)], fill=lc.TEXT_COLOR_HIGHLIGHT, width=1) # White
            draw.line([(0, ly), (WIDTH - 1, ly)], fill=lc.TEXT_COLOR_HIGHLIGHT, width=1) # White

        if debug_layout_enabled: # If both touch and layout debug are enabled
            # Draw active button touch zones (filled green rectangles)
            # These buttons are populated by the render_..._full_panel calls above for the current screen
            for button in active_buttons:
                draw.rectangle(button['rect'], fill=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT) # Green filled
    # --- End touch debug visuals ---

    push(img)

# ---------------------------------------------------------------------------
# Touch Input Handling
# ---------------------------------------------------------------------------
def _initialize_touch_device():
    global touch_device
    if not InputDevice: # evdev not imported
        return

    device_path_to_try = TOUCH_DEVICE_PATH
    if not device_path_to_try:
        print("TOUCH_DEVICE_PATH not set. Attempting to auto-detect touch device...", flush=True)
        try:
            devices = [InputDevice(path) for path in list_devices()]
            for dev_candidate in devices:
                cap = dev_candidate.capabilities(verbose=False)
                if ecodes.EV_KEY in cap and ecodes.BTN_TOUCH in cap[ecodes.EV_KEY] and \
                   ecodes.EV_ABS in cap and ecodes.ABS_X in cap[ecodes.EV_ABS] and \
                   ecodes.ABS_Y in cap[ecodes.EV_ABS]:
                    device_path_to_try = dev_candidate.path
                    print(f"Auto-detected touch device: {dev_candidate.name} at {device_path_to_try}", flush=True)
                    break
            if not device_path_to_try:
                print("Could not auto-detect a touch device. Touch input disabled.", flush=True)
                return
        except Exception as e:
            print(f"Error during touch device auto-detection: {e}. Touch input disabled.", flush=True)
            return


    try:
        touch_device = InputDevice(device_path_to_try)
        print(f"Successfully opened touch device: {touch_device.name} at {device_path_to_try}", flush=True)
        # Print device capabilities for debugging (optional)
        print(f"Device capabilities: {touch_device.capabilities(verbose=True)}", flush=True)
    except Exception as e:
        print(f"Error opening touch device {device_path_to_try}: {e}. Touch input disabled.", flush=True)
        touch_device = None

def _transform_touch_coordinates(raw_x: int, raw_y: int) -> Tuple[int, int]:
    """Transforms raw touch coordinates to logical screen coordinates based on rotation."""
    # fb.width and fb.height are the physical dimensions of the framebuffer (xres, yres)
    physical_width = fb.width
    physical_height = fb.height

    logical_x, logical_y = raw_x, raw_y # Default, will be overwritten by specific rotation logic

    # Apply new transformation logic based on observed axis swap and inversion
    if lc.ROTATE == 0:
        logical_x = physical_width - 1 - raw_y
        logical_y = raw_x
    elif lc.ROTATE == 90:
        logical_x = raw_x
        logical_y = raw_y
    elif lc.ROTATE == 180:
        logical_x = raw_y
        logical_y = physical_height - 1 - raw_x
    elif lc.ROTATE == 270:
        logical_x = physical_height - 1 - raw_x
        logical_y = physical_width - 1 - raw_y
    else: # Should not happen, but as a fallback
        logical_x = raw_x
        logical_y = raw_y


    # Scaling if touch device coordinates are different from screen pixels
    if touch_device and ecodes.EV_ABS in touch_device.capabilities():
        # Convert the list of (code, absinfo) tuples to a dictionary
        abs_event_capabilities = dict(touch_device.capabilities()[ecodes.EV_ABS])
        abs_info_x = abs_event_capabilities.get(ecodes.ABS_X)
        abs_info_y = abs_event_capabilities.get(ecodes.ABS_Y)

        if abs_info_x and abs_info_y:
            min_x, max_x = abs_info_x.min, abs_info_x.max
            min_y, max_y = abs_info_y.min, abs_info_y.max

            # Prevent division by zero if min == max
            if max_x == min_x or max_y == min_y:
                 # Cannot scale, assume 1:1 or log error
                print("Warning: Touch device reports min == max for X or Y axis. Cannot scale coordinates.", flush=True)
            else:
                # Use the original raw_x, raw_y for scaling calculation
                # before rotation transformation was applied to them as logical_x, logical_y
                # This is a bit tricky. The raw_x, raw_y are inputs to this function.
                # The rotation logic above assumes raw_x, raw_y are already in physical pixel space.
                # So, scaling should happen *before* rotation.
                # Let's redefine: scaled_raw_x, scaled_raw_y are the inputs after scaling.

                # Scaling is possible, recalculate logical_x, logical_y with scaling.
                # Calculate calibration error offsets in pixels
                cal_error_x_pixels = lc.CALIBRATION_ERROR_X_FACTOR * lc.BAR_HEIGHT
                cal_error_y_pixels = lc.CALIBRATION_ERROR_Y_FACTOR * lc.BAR_HEIGHT

                # Generic scaling function applying calibration
                def get_calibrated_scaled_value(raw_val, r_min, r_max, target_dim, cal_error_dim_pixels):
                    E = cal_error_dim_pixels
                    D_minus_1 = target_dim - 1 # Screen dimension span (e.g., width-1 or height-1)

                    # Denominator for the correction terms
                    denominator = D_minus_1 - (2 * E)

                    if denominator <= 0:
                        print(f"Warning: Touch calibration denominator ({denominator}) is not positive. Errors might be too large for this calibration model or screen dim too small. Check CALIBRATION_ERROR factors. Falling back to uncalibrated.", flush=True)
                        # Fallback to simple uncalibrated scaling
                        if (r_max - r_min) == 0: return D_minus_1 / 2.0 # Avoid div by zero if raw range is also zero
                        return (raw_val - r_min) * D_minus_1 / (r_max - r_min)

                    # Corrected output_min and output_span
                    # These are the target values that, when perceived with the error, should result in the ideal mapping.
                    output_min = -E * D_minus_1 / denominator
                    output_span = D_minus_1**2 / denominator
                    
                    # The rest of the scaling logic remains the same, using these corrected min/span
                    if (r_max - r_min) == 0: # Should have been caught by caller, but defensive check
                        print("Warning: Raw touch range (r_max - r_min) is zero in get_calibrated_scaled_value.", flush=True)
                        return output_min + output_span / 2.0 # Return midpoint of corrected target

                    scaled_val = ((raw_val - r_min) * output_span / (r_max - r_min)) + output_min
                    return scaled_val

                if lc.ROTATE == 0:
                    # raw_y contributes to screen X-dim (target: physical_width), use cal_error_x_pixels
                    # raw_x contributes to screen Y-dim (target: physical_height), use cal_error_y_pixels
                    scaled_y_input = get_calibrated_scaled_value(raw_y, min_y, max_y, physical_width, cal_error_x_pixels)
                    scaled_x_input = get_calibrated_scaled_value(raw_x, min_x, max_x, physical_height, cal_error_y_pixels)
                    
                    logical_x = physical_width - 1 - scaled_y_input
                    logical_y = scaled_x_input
                elif lc.ROTATE == 90:
                    # raw_x contributes to screen X-dim (target: physical_width), use cal_error_x_pixels
                    # raw_y contributes to screen Y-dim (target: physical_height), use cal_error_y_pixels
                    scaled_x_input = get_calibrated_scaled_value(raw_x, min_x, max_x, physical_width, cal_error_x_pixels)
                    scaled_y_input = get_calibrated_scaled_value(raw_y, min_y, max_y, physical_height, cal_error_y_pixels)

                    logical_x = scaled_x_input
                    logical_y = scaled_y_input
                elif lc.ROTATE == 180:
                    # raw_y contributes to screen X-dim (target: physical_width), use cal_error_x_pixels
                    # raw_x contributes to screen Y-dim (target: physical_height), use cal_error_y_pixels
                    scaled_y_input = get_calibrated_scaled_value(raw_y, min_y, max_y, physical_width, cal_error_x_pixels)
                    scaled_x_input = get_calibrated_scaled_value(raw_x, min_x, max_x, physical_height, cal_error_y_pixels)

                    logical_x = scaled_y_input
                    logical_y = physical_height - 1 - scaled_x_input
                elif lc.ROTATE == 270:
                    # raw_x contributes to screen Y-dim (logical_x after transformation, target: physical_height), use cal_error_y_pixels
                    # raw_y contributes to screen X-dim (logical_y after transformation, target: physical_width), use cal_error_x_pixels
                    scaled_x_input = get_calibrated_scaled_value(raw_x, min_x, max_x, physical_height, cal_error_y_pixels)
                    scaled_y_input = get_calibrated_scaled_value(raw_y, min_y, max_y, physical_width, cal_error_x_pixels)
                    
                    logical_x = physical_height - 1 - scaled_x_input
                    logical_y = physical_width - 1 - scaled_y_input
                else: # Fallback for unknown lc.ROTATE value
                    print(f"Warning: Unknown lc.ROTATE value {lc.ROTATE} in scaling. Defaulting to uncalibrated ROTATE=90 like scaling.", flush=True)
                    # Fallback to simpler, uncalibrated scaling for this unknown case
                    scaled_x_component = (raw_x - min_x) * physical_width / (max_x - min_x)
                    scaled_y_component = (raw_y - min_y) * physical_height / (max_y - min_y)
                    logical_x = scaled_x_component
                    logical_y = scaled_y_component


    return int(logical_x), int(logical_y)


def _handle_button_press(button_id: str):
    global current_display_mode
    print(f"Button pressed: {button_id}", flush=True)
    action_taken = False

    if button_id == 'btn_clear' and current_display_mode == "events":
        messages_store.clear()
        print("Event log CLEARED by touch", flush=True)
        action_taken = True
    elif button_id == 'btn_clock_mode' and current_display_mode == "events":
        current_display_mode = "clock"
        print("Switched to CLOCK mode by touch", flush=True)
        action_taken = True
    elif button_id == 'btn_events_mode' and current_display_mode == "clock":
        current_display_mode = "events"
        print("Switched to EVENTS mode by touch", flush=True)
        action_taken = True
    # Add other button IDs here if needed, e.g. 'btn_relative'

    if action_taken:
        refresh_display()

def _process_touch_event():
    global last_touch_x, last_touch_y
    if not touch_device or not ecodes:
        return

    try:
        while True: # Loop to read all currently available events
            event = touch_device.read_one()
            if event is None:
                break # No more events are immediately available

            # print(f"Touch event: {categorize(event)}", flush=True) # Very verbose
            if event.type == ecodes.EV_ABS:
                if event.code == ecodes.ABS_X:
                    last_touch_x = event.value
                elif event.code == ecodes.ABS_Y:
                    last_touch_y = event.value
            elif event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH and event.value == 1: # Touch down (press)
                if last_touch_x is not None and last_touch_y is not None:
                    # print(f"Raw touch down at: ({last_touch_x}, {last_touch_y})", flush=True)
                    logical_x, logical_y = _transform_touch_coordinates(last_touch_x, last_touch_y)
                    print(f"Touch event: raw ({last_touch_x},{last_touch_y}), transformed ({logical_x},{logical_y})", flush=True)

                    button_pressed_and_refreshed = False
                    if debug_touch_enabled: # Store coords early if debug is on
                        global last_debug_touch_coords
                        last_debug_touch_coords = (logical_x, logical_y)

                    for button in active_buttons:
                        x1, y1, x2, y2 = button['rect']
                        if x1 <= logical_x <= x2 and y1 <= logical_y <= y2:
                            _handle_button_press(button['id']) # This calls refresh_display()
                            button_pressed_and_refreshed = True
                            # It's possible BTN_TOUCH release (value 0) or other EV_ABS events might follow.
                            # For simple tap, acting on press is usually fine.
                            # Consider clearing last_touch_x/y on BTN_TOUCH release if needed.
                            break # Found a button, no need to check others for this press event
                    
                    if debug_touch_enabled and not button_pressed_and_refreshed:
                        # If no button was pressed (which would trigger its own refresh),
                        # but touch debugging is on, refresh to show the touch point.
                        # last_debug_touch_coords is already set from above.
                        refresh_display()
    except BlockingIOError:
        # This can happen with read_one() if no event is available, though it typically returns None.
        # It's safe to just pass and try again later.
        pass
    except Exception as e:
        print(f"Error reading from touch device: {e}", flush=True)
        # Consider re-initializing or disabling touch if errors persist
        # For now, just log and continue.

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
    global debug_layout_enabled, log_control_messages_enabled, current_display_mode, debug_touch_enabled, last_debug_touch_coords
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
            elif command_suffix == "debug-touch":
                if payload_str == "enable":
                    if not debug_touch_enabled: # Check current state to avoid redundant operations
                        debug_touch_enabled = True
                        print("Touch debugging ENABLED", flush=True)
                        # Refresh to potentially show button zones if layout debug also on,
                        # or to show a previous touch point if one was made while disabled.
                        needs_render = True
                elif payload_str == "disable" or payload_str == "":
                    if debug_touch_enabled: # Check current state
                        debug_touch_enabled = False
                        last_debug_touch_coords = None # Clear last touch coords when disabling
                        print("Touch debugging DISABLED", flush=True)
                        needs_render = True # Refresh to clear any existing touch debug visuals
                else:
                    print(f"Unknown payload for debug-touch: '{payload_str}'", flush=True)
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
            elif command_suffix == "clear-events":
                messages_store.clear()
                print("All event log messages CLEARED", flush=True)
                if current_display_mode == "events": # Only need to re-render if in events mode
                    needs_render = True
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

    _initialize_touch_device() # Initialize touch device early

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
        if client and client.is_connected():
            client.loop_stop()                     # Stop MQTT network thread
        blank()                                # Clear screen (safe if FB already closed)
        if touch_device:
            try:
                touch_device.close()
                print("Touch device closed.", flush=True)
            except Exception as e:
                print(f"Error closing touch device: {e}", flush=True)
        fb.close()                             # Release framebuffer resources
        sys.exit(0)
    signal.signal(signal.SIGINT, bye)
    signal.signal(signal.SIGTERM, bye)

    print("Main loop starting. Press Ctrl+C to exit.", flush=True)
    try:
        while not _exit_in_progress: # Check _exit_in_progress flag
            _process_touch_event() # Check for touch events first

            if current_display_mode == "clock":
                # Clock mode updates itself based on time, so refresh frequently
                refresh_display() # This clears and repopulates active_buttons

                now = datetime.now()
                sleep_for_alignment = (1_000_000 - now.microsecond) / 1_000_000.0
                actual_sleep_time = max(0.01, sleep_for_alignment) # Min 10ms sleep
                time.sleep(actual_sleep_time)
            else:
                # Event log mode only needs to refresh on new messages (handled by on_mqtt)
                # or touch events (handled by _process_touch_event -> _handle_button_press -> refresh_display).
                # So, just sleep for a bit to yield CPU and allow touch/MQTT to be processed.
                # A short sleep allows responsiveness to touch.
                time.sleep(0.05) # 50ms sleep, adjust as needed for responsiveness vs CPU usage

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
