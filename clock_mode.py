from datetime import datetime
from collections import deque
from typing import List, Deque, Dict, Any, Optional, Tuple
import os, textwrap
import zoneinfo
try:
    import tzlocal
except ImportError:
    tzlocal = None

import lcars_constants as lc
from framebuffer_utils import WIDTH, HEIGHT
from lcars_drawing_utils import text_size, draw_text_in_rect
from lcars_ui_components import render_top_bar, render_bottom_bar

def _get_timezone_details_str() -> str:
    try:
        dt_now_local = datetime.now().astimezone()
        tz_name_full = ""
        if tzlocal:
            try:
                tz_name_full = tzlocal.get_localzone_name()
            except Exception:
                tz_name_full = str(dt_now_local.tzinfo)
        else:
            try:
                if hasattr(dt_now_local.tzinfo, 'key'):
                    tz_name_full = dt_now_local.tzinfo.key
                else:
                    tz_name_full = dt_now_local.tzname() if dt_now_local.tzname() else str(dt_now_local.tzinfo)
            except Exception:
                tz_name_full = str(dt_now_local.tzinfo)

        abbreviation = dt_now_local.tzname() if dt_now_local.tzname() else ""

        offset_timedelta = dt_now_local.utcoffset()
        if offset_timedelta is not None:
            total_seconds = offset_timedelta.total_seconds()
            offset_hours = int(total_seconds // 3600)
            offset_minutes = int((total_seconds % 3600) // 60)
            utc_offset_str = f"UTC{offset_hours:+03d}:{offset_minutes:02d}"
        else:
            utc_offset_str = "UTC"

        if tz_name_full == abbreviation:
            return f"{tz_name_full} - {utc_offset_str}"
        return f"{tz_name_full} - {abbreviation} - {utc_offset_str}"

    except Exception as e:
        print(f"Error getting timezone details: {e}", flush=True)
        try:
            dt_now_local = datetime.now().astimezone()
            return f"{dt_now_local.tzname()} {dt_now_local.strftime('%z')}"
        except:
            return "Local Time"

def _get_max_font_for_text_and_space(draw, text, font_path, target_height, target_width,
                                     initial_font_size=120, min_font_size=10, font_size_step=2) -> Tuple[Optional[Any], int, int]:
    if not text or target_height <= 0 or target_width <= 0:
        return None, 0, 0

    current_size = initial_font_size
    best_font = None
    last_w, last_h = 0, 0

    from PIL import ImageFont

    while current_size >= min_font_size:
        try:
            font = ImageFont.truetype(font_path, current_size)
            text_w, text_h = text_size(draw, text, font)

            if text_h <= target_height and text_w <= target_width:
                best_font = font
                last_w, last_h = text_w, text_h
                break
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
    else:
        try:
            font = ImageFont.truetype(font_path, min_font_size)
            text_w_min, text_h_min = text_size(draw, text, font)
            return font, text_w_min, text_h_min
        except:
            return None, 0, 0

def _calculate_message_area_layout(draw):
    layout = {}
    layout['message_area_y_start'] = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING
    layout['message_area_y_end'] = HEIGHT - lc.PADDING - lc.BAR_HEIGHT - lc.PADDING
    layout['message_area_height'] = layout['message_area_y_end'] - layout['message_area_y_start']
    layout['message_line_height'] = lc.BODY_FONT.size + 4
    return layout

def render_clock_content_area(draw, layout, debug_layout_enabled):
    content_area_x = lc.PADDING * 2
    content_area_y = layout['message_area_y_start']
    content_area_width = WIDTH - (2 * lc.PADDING * 2)
    content_area_height = layout['message_area_height']

    if content_area_width <=0 or content_area_height <=0: return

    font_path = lc.BODY_FONT.path if hasattr(lc.BODY_FONT, 'path') and lc.BODY_FONT.path and os.path.exists(lc.BODY_FONT.path) else None
    if not font_path and lc.DEFAULT_LCARS_FONT_PATH and os.path.exists(lc.DEFAULT_LCARS_FONT_PATH):
        font_path = lc.DEFAULT_LCARS_FONT_PATH
    if not font_path and lc.LCARS_FONT_PATH and os.path.exists(lc.LCARS_FONT_PATH):
        font_path = lc.LCARS_FONT_PATH
    if not font_path:
        font_path = lc.FALLBACK_FONT_PATH

    time_area_height = int(content_area_height * 0.6)
    time_str = datetime.now().strftime("%H:%M:%S")
    time_font, time_w, time_h = _get_max_font_for_text_and_space(
        draw, time_str, font_path, time_area_height, content_area_width,
        initial_font_size=max(100, int(time_area_height * 0.8))
    )

    if time_font:
        time_x = content_area_x + (content_area_width - time_w) // 2
        time_y = content_area_y + (time_area_height - time_h) // 2
        draw.text((time_x, time_y), time_str, font=time_font, fill=lc.TEXT_COLOR_TITLE, anchor="lt")
        if debug_layout_enabled:
            draw.rectangle((time_x, time_y, time_x + time_w, time_y + time_h), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)
            draw.rectangle((content_area_x, content_area_y, content_area_x + content_area_width -1 , content_area_y + time_area_height -1), outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1)

    date_area_y_start = content_area_y + time_area_height
    date_area_height = content_area_height - time_area_height
    date_str = datetime.now().strftime("%Y-%m-%d - %A")
    date_font, date_w, date_h = _get_max_font_for_text_and_space(
        draw, date_str, font_path, date_area_height, content_area_width,
        initial_font_size=max(40, int(date_area_height * 0.7))
    )

    if date_font:
        date_x = content_area_x + (content_area_width - date_w) // 2
        date_y = date_area_y_start + (date_area_height - date_h) // 2
        draw.text((date_x, date_y), date_str, font=date_font, fill=lc.TEXT_COLOR_BODY, anchor="lt")
        if debug_layout_enabled:
            draw.rectangle((date_x, date_y, date_x + date_w, date_y + date_h), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)
            draw.rectangle((content_area_x, date_area_y_start, content_area_x + content_area_width -1, date_area_y_start + date_area_height -1), outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1)

def render_clock_full_panel(img, draw, active_buttons_list: List[Dict[str, Any]], debug_layout_enabled):
    render_top_bar(draw, WIDTH, "CURRENT TIME", debug_layout_enabled=debug_layout_enabled)

    timezone_label_text = _get_timezone_details_str()
    clock_mode_buttons_config = [
        {'text': "EVENTS", 'color': lc.COLOR_BUTTON_RELATIVE, 'id': 'btn_events_mode'}
    ]
    render_bottom_bar(draw, WIDTH, HEIGHT,
                      label_text=timezone_label_text,
                      buttons_config=clock_mode_buttons_config,
                      active_buttons_list=active_buttons_list,
                      debug_layout_enabled=debug_layout_enabled)

    layout = _calculate_message_area_layout(draw)
    render_clock_content_area(draw, layout, debug_layout_enabled)
