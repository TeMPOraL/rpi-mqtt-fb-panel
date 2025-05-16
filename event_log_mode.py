from datetime import datetime
from collections import deque
from typing import List, Deque, Dict, Any
import os, textwrap

import lcars_constants as lc
from framebuffer_utils import WIDTH, HEIGHT
from lcars_drawing_utils import text_size, draw_text_in_rect
from lcars_ui_components import render_top_bar, render_bottom_bar

MESSAGE_AREA_HORIZONTAL_PADDING = lc.PADDING * 2

def _calculate_message_area_layout(draw):
    layout = {}
    layout['message_area_y_start'] = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING
    layout['message_area_y_end'] = HEIGHT - lc.PADDING - lc.BAR_HEIGHT - lc.PADDING
    layout['message_area_height'] = layout['message_area_y_end'] - layout['message_area_y_start']
    layout['message_line_height'] = lc.BODY_FONT.size + 4

    col_source_max_chars = 20
    m_char_width_tuple = text_size(draw, "M", lc.BODY_FONT)
    m_char_width = m_char_width_tuple[0] if m_char_width_tuple[0] > 0 else lc.BODY_FONT.size * 0.6

    sample_text_for_avg = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789"
    avg_sample_width, _ = text_size(draw, sample_text_for_avg, lc.BODY_FONT)

    if avg_sample_width > 0 and len(sample_text_for_avg) > 0:
        layout['avg_char_width_message'] = avg_sample_width / len(sample_text_for_avg)
    elif m_char_width > 0:
        layout['avg_char_width_message'] = m_char_width * 0.7
    else:
        layout['avg_char_width_message'] = max(1, lc.BODY_FONT.size * 0.5)

    layout['col_source_width'] = int(min(WIDTH * 0.25, col_source_max_chars * m_char_width + lc.PADDING))

    col_time_text_example = "00:00:00"
    layout['col_time_width'] = text_size(draw, col_time_text_example, lc.BODY_FONT)[0] + lc.PADDING

    layout['col_source_x'] = MESSAGE_AREA_HORIZONTAL_PADDING
    layout['col_message_x'] = layout['col_source_x'] + layout['col_source_width'] + lc.PADDING

    layout['col_message_width'] = (WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - layout['col_time_width'] - lc.PADDING) - layout['col_message_x']

    return layout

def _process_messages_for_display(draw, messages_to_process, layout):
    processed_message_lines = []
    col_source_max_chars = 20

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

def render_event_log_content_area(draw, layout, messages_store, debug_layout_enabled):
    if debug_layout_enabled:
        draw.rectangle(
            (layout['col_source_x'], layout['message_area_y_start'],
             layout['col_source_x'] + layout['col_source_width'] -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )
        draw.rectangle(
            (layout['col_message_x'], layout['message_area_y_start'],
             layout['col_message_x'] + layout['col_message_width'] -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )
        time_col_x_start = WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING - layout['col_time_width']
        draw.rectangle(
            (time_col_x_start, layout['message_area_y_start'],
             WIDTH - MESSAGE_AREA_HORIZONTAL_PADDING -1, layout['message_area_y_end'] -1),
            outline=lc.DEBUG_BOUNDING_BOX_MESSAGE_COLUMN, width=1
        )
        wrap_line_x = layout['col_message_x'] + layout['col_message_width']
        draw.line(
            [(wrap_line_x, layout['message_area_y_start']),
             (wrap_line_x, layout['message_area_y_end'] -1)],
            fill=lc.DEBUG_MESSAGE_WRAP_LINE_COLOR, width=1
        )

    current_messages_snapshot = list(messages_store)
    processed_message_lines = _process_messages_for_display(draw, current_messages_snapshot, layout)

    lines_to_render_on_screen = []
    if layout['message_line_height'] > 0 and layout['message_area_height'] > 0:
        max_displayable_message_lines = layout['message_area_height'] // layout['message_line_height']
        if max_displayable_message_lines > 0:
            lines_to_render_on_screen = processed_message_lines[-max_displayable_message_lines:]

    current_render_y = layout['message_area_y_start']
    for line_data in lines_to_render_on_screen:
        if current_render_y + lc.BODY_FONT.size > layout['message_area_y_end']:
            break

        line_importance = line_data.get("importance", "info")
        text_fill_color = lc.TEXT_COLOR_BODY
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

def render_event_log_full_panel(img, draw, messages_store, debug_layout_enabled):
    render_top_bar(draw, WIDTH, "EVENT LOG", debug_layout_enabled)

    event_log_buttons = [
        {'text': "CLEAR", 'color': lc.COLOR_BUTTON_CLEAR, 'id': 'btn_clear'},
        {'text': "RELATIVE", 'color': lc.COLOR_BUTTON_RELATIVE, 'id': 'btn_relative'},
        {'text': "CLOCK", 'color': lc.COLOR_BUTTON_CLOCK, 'id': 'btn_clock_mode'}
    ]
    render_bottom_bar(draw, WIDTH, HEIGHT, "MQTT STREAM", event_log_buttons, debug_layout_enabled)

    layout = _calculate_message_area_layout(draw)
    render_event_log_content_area(draw, layout, messages_store, debug_layout_enabled)
