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
from lcars_drawing_utils import text_size, draw_text_in_rect # Added draw_text_in_rect for potential use
from lcars_ui_components import render_top_bar, render_bottom_bar


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
    # Estimate source col width based on M chars (for source column sizing)
    m_char_width_tuple = text_size(draw, "M", lc.BODY_FONT)
    m_char_width = m_char_width_tuple[0] if m_char_width_tuple[0] > 0 else lc.BODY_FONT.size * 0.6 # Fallback for M width

    # For message wrapping, use a more representative average character width
    sample_text_for_avg = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789"
    avg_sample_width, _ = text_size(draw, sample_text_for_avg, lc.BODY_FONT)

    if avg_sample_width > 0 and len(sample_text_for_avg) > 0:
        layout['avg_char_width_message'] = avg_sample_width / len(sample_text_for_avg)
    elif m_char_width > 0: # If 'M' width is available and sample calculation failed
        # Estimate average as a fraction of 'M' width, smaller than 'M' itself
        layout['avg_char_width_message'] = m_char_width * 0.7
    else: # Absolute fallback if 'M' width is also zero or unavailable
        layout['avg_char_width_message'] = max(1, lc.BODY_FONT.size * 0.5)

    # layout['col_source_width'] uses m_char_width for its estimation
    layout['col_source_width'] = int(min(WIDTH * 0.25, col_source_max_chars * m_char_width + lc.PADDING))

    col_time_text_example = "00:00:00"
    layout['col_time_width'] = text_size(draw, col_time_text_example, lc.BODY_FONT)[0] + lc.PADDING

    layout['col_source_x'] = MESSAGE_AREA_HORIZONTAL_PADDING
    layout['col_message_x'] = layout['col_source_x'] + layout['col_source_width'] + lc.PADDING
    
    layout['col_message_width'] = (WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - layout['col_time_width'] - lc.PADDING) - layout['col_message_x']
    
    return layout

# ---------------------------------------------------------------------------
# Timezone and Font Helper Functions
# ---------------------------------------------------------------------------
def _get_timezone_details_str() -> str:
    """Generates a timezone string like 'Europe/Warsaw - CEST - UTC+02:00'."""
    try:
        dt_now_local = datetime.now().astimezone()
        tz_name_full = ""
        if tzlocal:
            try:
                tz_name_full = tzlocal.get_localzone_name()
            except Exception: # tzlocal can sometimes fail
                tz_name_full = str(dt_now_local.tzinfo) # Fallback to tzinfo string
        else: # tzlocal not available
             # Try to get a ZoneInfo key if possible, otherwise just use tzname()
            try:
                # This is a guess; dt_now_local.tzinfo might not have a 'key'
                # and tzname() is often just an abbreviation.
                if hasattr(dt_now_local.tzinfo, 'key'): # type: ignore
                     tz_name_full = dt_now_local.tzinfo.key # type: ignore
                else: # Fallback if no key
                    tz_name_full = dt_now_local.tzname() if dt_now_local.tzname() else str(dt_now_local.tzinfo)

            except Exception:
                 tz_name_full = str(dt_now_local.tzinfo) # Last resort fallback

        abbreviation = dt_now_local.tzname() if dt_now_local.tzname() else ""
        
        offset_timedelta = dt_now_local.utcoffset()
        if offset_timedelta is not None:
            total_seconds = offset_timedelta.total_seconds()
            offset_hours = int(total_seconds // 3600)
            offset_minutes = int((total_seconds % 3600) // 60)
            utc_offset_str = f"UTC{offset_hours:+03d}:{offset_minutes:02d}"
        else:
            utc_offset_str = "UTC" # Should not happen with astimezone()

        # Filter out potentially redundant abbreviation if it's same as full name (e.g. for "UTC")
        if tz_name_full == abbreviation:
            return f"{tz_name_full} - {utc_offset_str}"
        return f"{tz_name_full} - {abbreviation} - {utc_offset_str}"

    except Exception as e:
        print(f"Error getting timezone details: {e}", flush=True)
        # Fallback to simpler local time info if complex parsing fails
        try:
            dt_now_local = datetime.now().astimezone()
            return f"{dt_now_local.tzname()} {dt_now_local.strftime('%z')}"
        except: # Final fallback
            return "Local Time"


def _get_max_font_for_text_and_space(draw: ImageDraw.ImageDraw, text: str, font_path: str,
                                     target_height: int, target_width: int,
                                     initial_font_size: int = 120, min_font_size: int = 10,
                                     font_size_step: int = 2) -> Tuple[Optional[ImageFont.FreeTypeFont], int, int]:
    """
    Finds the largest font size where 'text' fits within 'target_height' and 'target_width'.
    Returns (font, text_w, text_h) or (None, 0, 0) if no fit.
    """
    if not text or target_height <= 0 or target_width <= 0:
        return None, 0, 0

    current_size = initial_font_size
    best_font: Optional[ImageFont.FreeTypeFont] = None
    last_w, last_h = 0, 0

    while current_size >= min_font_size:
        try:
            font = ImageFont.truetype(font_path, current_size)
            text_w, text_h = text_size(draw, text, font)

            if text_h <= target_height and text_w <= target_width:
                best_font = font
                last_w, last_h = text_w, text_h
                break # Found a fit
            # Store last attempt for debug or if no fit, even if it didn't fit
            last_w, last_h = text_w, text_h 
        except IOError: 
            print(f"Warning: Could not load font {font_path} at size {current_size}", flush=True)
            pass 
        except Exception as e:
            print(f"Error loading font or getting text size: {e}", flush=True)
            pass

        current_size -= font_size_step
    
    if best_font:
        return best_font, last_w, last_h
    else: # No font found that fits, try to return the smallest one attempted
        try: 
            font = ImageFont.truetype(font_path, min_font_size)
            # Recalculate w,h for this smallest font, as last_w, last_h might be from a larger non-fitting one
            text_w_min, text_h_min = text_size(draw, text, font)
            return font, text_w_min, text_h_min 
        except:
            return None, 0, 0 # Absolute fallback

# ---------------------------------------------------------------------------
# Message Processing for Display (Event Log)
# ---------------------------------------------------------------------------
def _process_messages_for_display(draw: ImageDraw.ImageDraw, messages_to_process: List[Message], layout: dict) -> List[dict]:
    """Formats and wraps messages from the store into lines suitable for display (Event Log)."""
    processed_message_lines = []
    col_source_max_chars = 20 # Should ideally come from layout or be a constant

    for msg_obj in messages_to_process:
        ts_str = msg_obj.timestamp.strftime("%H:%M:%S")
        importance = msg_obj.importance

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
            "source": source_text, "msg_part": wrapped_message_lines[0], "time": ts_str, "importance": importance
        })
        for line_part in wrapped_message_lines[1:]:
            processed_message_lines.append({
                "source": "", "msg_part": line_part, "time": "", "importance": importance
            })
    return processed_message_lines

# ---------------------------------------------------------------------------
# Mode-Specific Content Area Renderers
# ---------------------------------------------------------------------------
def render_event_log_content_area(draw: ImageDraw.ImageDraw, layout: dict):
    """Renders the rolling list of messages for the Event Log mode."""
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
        # Message wrap debug line
        wrap_line_x = layout['col_message_x'] + layout['col_message_width']
        draw.line(
            [(wrap_line_x, layout['message_area_y_start']),
             (wrap_line_x, layout['message_area_y_end'] -1)],
            fill=lc.DEBUG_MESSAGE_WRAP_LINE_COLOR, width=1
        )

    # Prepare Messages for Display
    current_messages_snapshot = list(messages_store) 
    processed_message_lines = _process_messages_for_display(draw, current_messages_snapshot, layout)

    # Calculate how many lines fit and get the latest ones
    lines_to_render_on_screen = []
    if layout['message_line_height'] > 0 and layout['message_area_height'] > 0:
        max_displayable_message_lines = layout['message_area_height'] // layout['message_line_height']
        if max_displayable_message_lines > 0:
            lines_to_render_on_screen = processed_message_lines[-max_displayable_message_lines:]

    # Draw the messages
    current_render_y = layout['message_area_y_start']
    for line_data in lines_to_render_on_screen:
        if current_render_y + lc.BODY_FONT.size > layout['message_area_y_end']: # Check using BODY_FONT.size for actual text height
            break
        
        line_importance = line_data.get("importance", "info")
        text_fill_color = lc.TEXT_COLOR_BODY # Default
        if line_importance == "control": text_fill_color = lc.TEXT_COLOR_CONTROL
        elif line_importance == "error": text_fill_color = lc.TEXT_COLOR_ERROR
        elif line_importance == "warning": text_fill_color = lc.TEXT_COLOR_WARNING

        if line_data["source"]:
            draw.text((layout['col_source_x'], current_render_y), line_data["source"], font=lc.BODY_FONT, fill=text_fill_color)
        draw.text((layout['col_message_x'], current_render_y), line_data["msg_part"], font=lc.BODY_FONT, fill=text_fill_color)
        if line_data["time"]:
            time_w, _ = text_size(draw, line_data["time"], lc.BODY_FONT)
            actual_time_x = WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - time_w
            draw.text((actual_time_x, current_render_y), line_data["time"], font=lc.BODY_FONT, fill=text_fill_color)
        current_render_y += layout['message_line_height']

def render_clock_content_area(draw: ImageDraw.ImageDraw, layout: dict):
    """Renders the time and date for the Clock mode."""
    content_area_x = MESSAGE_AREA_HORIZONTAL_PADDING 
    content_area_y = layout['message_area_y_start']
    content_area_width = WIDTH - (2 * MESSAGE_AREA_HORIZONTAL_PADDING)
    content_area_height = layout['message_area_height']

    if content_area_width <=0 or content_area_height <=0: return

    font_path = lc.BODY_FONT.path if hasattr(lc.BODY_FONT, 'path') and lc.BODY_FONT.path and os.path.exists(lc.BODY_FONT.path) else None
    if not font_path and lc.DEFAULT_LCARS_FONT_PATH and os.path.exists(lc.DEFAULT_LCARS_FONT_PATH):
        font_path = lc.DEFAULT_LCARS_FONT_PATH
    if not font_path and lc.LCARS_FONT_PATH and os.path.exists(lc.LCARS_FONT_PATH):
        font_path = lc.LCARS_FONT_PATH
    if not font_path: # Absolute fallback if no valid path found
        font_path = lc.FALLBACK_FONT_PATH # Assumes FALLBACK_FONT_PATH is generally available

    # Time (Top 60%)
    time_area_height = int(content_area_height * 0.6)
    time_str = datetime.now().strftime("%H:%M:%S")
    # Initial font size for time can be aggressive, e.g., target_height, or a large fixed number
    time_font, time_w, time_h = _get_max_font_for_text_and_space(
        draw, time_str, font_path, time_area_height, content_area_width, 
        initial_font_size=max(100, int(time_area_height * 0.8)) # Start with 80% of available height
    )
    
    if time_font:
        # Center the text block (w,h) within its allocated area (time_area_height, content_area_width)
        time_x = content_area_x + (content_area_width - time_w) // 2
        time_y = content_area_y + (time_area_height - time_h) // 2 
        draw.text((time_x, time_y), time_str, font=time_font, fill=lc.TEXT_COLOR_TITLE, anchor="lt") 
        if debug_layout_enabled:
            draw.rectangle((time_x, time_y, time_x + time_w, time_y + time_h), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)
            draw.rectangle((content_area_x, content_area_y, content_area_x + content_area_width -1 , content_area_y + time_area_height -1), outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1)

    # Date (Bottom 40%)
    date_area_y_start = content_area_y + time_area_height
    date_area_height = content_area_height - time_area_height
    date_str = datetime.now().strftime("%Y-%m-%d - %A") 
    date_font, date_w, date_h = _get_max_font_for_text_and_space(
        draw, date_str, font_path, date_area_height, content_area_width, 
        initial_font_size=max(40, int(date_area_height * 0.7)) # Start with 70% of available height
    )

    if date_font:
        date_x = content_area_x + (content_area_width - date_w) // 2
        date_y = date_area_y_start + (date_area_height - date_h) // 2
        draw.text((date_x, date_y), date_str, font=date_font, fill=lc.TEXT_COLOR_BODY, anchor="lt")
        if debug_layout_enabled:
            draw.rectangle((date_x, date_y, date_x + date_w, date_y + date_h), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)
            draw.rectangle((content_area_x, date_area_y_start, content_area_x + content_area_width -1, date_area_y_start + date_area_height -1), outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1)

# ---------------------------------------------------------------------------
# Mode-Specific Full Panel Renderers
# ---------------------------------------------------------------------------
def render_event_log_full_panel(img: Image.Image, draw: ImageDraw.ImageDraw):
    """Renders the entire Event Log panel."""
    render_top_bar(draw, WIDTH, "EVENT LOG", debug_layout_enabled)
    
    event_log_buttons = [
        {'text': "CLEAR", 'color': lc.COLOR_BUTTON_CLEAR, 'id': 'btn_clear'},
        {'text': "RELATIVE", 'color': lc.COLOR_BUTTON_RELATIVE, 'id': 'btn_relative'},
        {'text': "CLOCK", 'color': lc.COLOR_BUTTON_CLOCK, 'id': 'btn_clock_mode'}
    ]
    render_bottom_bar(draw, WIDTH, HEIGHT, "MQTT STREAM", event_log_buttons, debug_layout_enabled)
    
    layout = _calculate_message_area_layout(draw) 
    render_event_log_content_area(draw, layout)

def render_clock_full_panel(img: Image.Image, draw: ImageDraw.ImageDraw):
    """Renders the entire Clock panel."""
    render_top_bar(draw, WIDTH, "CURRENT TIME", debug_layout_enabled=debug_layout_enabled)

    timezone_label_text = _get_timezone_details_str()
    clock_mode_buttons_config = [
        {'text': "EVENTS", 'color': lc.COLOR_BUTTON_RELATIVE, 'id': 'btn_events_mode'} # Using a distinct color, e.g. blue
    ]
    render_bottom_bar(draw, WIDTH, HEIGHT, 
                      label_text=timezone_label_text, 
                      buttons_config=clock_mode_buttons_config, 
                      debug_layout_enabled=debug_layout_enabled)

    layout = _calculate_message_area_layout(draw) 
    render_clock_content_area(draw, layout)

# ---------------------------------------------------------------------------
# Main Rendering Dispatcher
# ---------------------------------------------------------------------------
def refresh_display():
    """Clears screen and renders the current mode's panel."""
    img = Image.new("RGB", (WIDTH, HEIGHT), lc.BG_COLOUR)
    draw = ImageDraw.Draw(img)

    if current_display_mode == "events":
        render_event_log_full_panel(img, draw)
    elif current_display_mode == "clock":
        render_clock_full_panel(img, draw)
    else: 
        print(f"Error: Unknown display mode '{current_display_mode}'. Defaulting to Event Log.", flush=True)
        render_event_log_full_panel(img, draw)

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
        print("Exiting...", flush=True)
        client.loop_stop() # Stop MQTT loop
        blank() # Clear screen on exit
        fb.close()
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
                microseconds_to_next_second = (1_000_000 - now.microsecond) / 1_000_000.0
                sleep_duration = microseconds_to_next_second
                
                # Ensure a minimum sleep if calculation/render overran the second
                # or to prevent extremely tight loops if microseconds_to_next_second is tiny.
                if sleep_duration <= 0.05: # e.g. if less than 50ms to next second or already past
                    sleep_duration = 1.0 + microseconds_to_next_second # Sleep until next second + a tiny bit into it
                
                time.sleep(max(0.01, sleep_duration)) # Minimum 10ms sleep to yield CPU
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
