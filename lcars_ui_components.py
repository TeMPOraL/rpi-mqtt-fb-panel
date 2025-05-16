from PIL import ImageDraw, ImageFont
import lcars_constants as lc
from lcars_drawing_utils import draw_lcars_shape, draw_text_in_rect, text_size
from typing import List, Dict, Any

def render_top_bar(draw: ImageDraw.ImageDraw, screen_width: int, title_text: str, debug_layout_enabled: bool = False):
    """Renders the top LCARS bar with a dynamic title."""
    # Left Terminator (])
    left_terminator_width = lc.BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, lc.PADDING, lc.PADDING, left_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, left_round=True, debug_draw_bbox=debug_layout_enabled)

    # Right Terminator [)
    right_terminator_width = lc.BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, screen_width - lc.PADDING - right_terminator_width, lc.PADDING, right_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, right_round=True, debug_draw_bbox=debug_layout_enabled)

    # "EVENT LOG" Text and associated Bar Segment
    # The Left and Right Terminators are drawn by the code immediately preceding this block.
    # This section calculates the position for the "EVENT LOG" text, draws it,
    # and then draws a bar segment filling the space between the Left Terminator and the text.

    event_log_text = "EVENT LOG"
    event_log_text_w, _ = text_size(draw, event_log_text, lc.TITLE_FONT)

    # Determine X position for "EVENT LOG" text (left edge).
    # The right edge of the text should be lc.PADDING to the left of the Right Terminator's starting X.
    text_x_coordinate = (screen_width - lc.PADDING - lc.BAR_HEIGHT) - lc.PADDING - event_log_text_w
    
    # Calculate Y position for the baseline of "EVENT LOG" text.
    # For TITLE_FONT within a BAR_HEIGHT sized to it, the baseline is at the bottom of the bar.
    # lc.PADDING is the Y offset for the top bar itself.
    event_log_baseline_y = lc.PADDING + lc.BAR_HEIGHT
    
    # Draw the "EVENT LOG" text directly on the background, using "ls" (left-baseline) anchor.
    # For debug drawing, we'll wrap this in draw_text_in_rect if we want its bounding box.
    # However, direct draw.text doesn't have a bbox option. For now, only elements using draw_lcars_shape or draw_text_in_rect get bboxes.
    # If precise bbox for this text is needed, it would require refactoring to use draw_text_in_rect or similar.
    draw.text((text_x_coordinate, event_log_baseline_y), event_log_text, font=lc.TITLE_FONT, fill=lc.TEXT_COLOR_TITLE, anchor="ls")
    if debug_layout_enabled: # Manual bbox for this specific text element
        event_log_text_h = lc.TITLE_FONT.getmask("A").size[1] # Approx height
        draw.rectangle((text_x_coordinate, event_log_baseline_y - event_log_text_h, 
                        text_x_coordinate + event_log_text_w, event_log_baseline_y), 
                       outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)


    # Draw the Main Bar Segment.
    # It starts lc.PADDING after the Left Terminator and ends lc.PADDING before the "EVENT LOG" text.
    # Left Terminator: x=lc.PADDING, width=lc.BAR_HEIGHT. So it ends at lc.PADDING + lc.BAR_HEIGHT.
    bar_segment_start_x = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING # Add lc.PADDING gap
    
    # The bar segment should end lc.PADDING to the left of where the "EVENT LOG" text starts.
    bar_segment_end_x = text_x_coordinate - lc.PADDING
    
    bar_segment_width = bar_segment_end_x - bar_segment_start_x

    if bar_segment_width > 0:
        draw_lcars_shape(draw, bar_segment_start_x, lc.PADDING, bar_segment_width, lc.BAR_HEIGHT, 0, lc.COLOR_BARS, debug_draw_bbox=debug_layout_enabled)

def render_bottom_bar(draw: ImageDraw.ImageDraw, screen_width: int, screen_height: int, 
                      label_text: str, buttons_config: List[Dict[str, Any]], 
                      debug_layout_enabled: bool = False):
    """Renders the bottom LCARS bar with a dynamic label and buttons."""
    BOTTOM_BAR_Y = screen_height - lc.PADDING - lc.BAR_HEIGHT
    left_terminator_width = lc.BAR_HEIGHT # Same as top bar

    # Left Terminator (]) for bottom bar
    draw_lcars_shape(draw, lc.PADDING, BOTTOM_BAR_Y, left_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, left_round=True, debug_draw_bbox=debug_layout_enabled)

    # current_x tracks the starting X for the next element, including lc.PADDING from the previous one.
    current_x = lc.PADDING + left_terminator_width + lc.PADDING

    # "MQTT STREAM" Text (No background bar)
    mqtt_stream_text = "MQTT STREAM"
    mqtt_stream_text_w, _ = text_size(draw, mqtt_stream_text, lc.TITLE_FONT)
    
    # Calculate X for centering the text based on its own width.
    # The text starts at current_x. Anchor "ms" uses the center of the text.
    mqtt_stream_text_center_x = current_x + mqtt_stream_text_w // 2
    mqtt_stream_baseline_y = BOTTOM_BAR_Y + lc.BAR_HEIGHT
    
    draw.text((mqtt_stream_text_center_x, mqtt_stream_baseline_y), 
              mqtt_stream_text, 
              font=lc.TITLE_FONT,
              fill=lc.TEXT_COLOR_TITLE,
              anchor="ms")
    if debug_layout_enabled: # Manual bbox for this specific text element
        mqtt_stream_text_h = lc.TITLE_FONT.getmask("A").size[1] # Approx height
        # For "ms" anchor, text_center_x is the horizontal center.
        # Baseline y is BOTTOM_BAR_Y + lc.BAR_HEIGHT. Top of text is roughly baseline_y - h.
        draw.rectangle((mqtt_stream_text_center_x - mqtt_stream_text_w // 2, BOTTOM_BAR_Y + lc.BAR_HEIGHT - mqtt_stream_text_h,
                        mqtt_stream_text_center_x + mqtt_stream_text_w // 2, BOTTOM_BAR_Y + lc.BAR_HEIGHT),
                       outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)

    current_x += mqtt_stream_text_w + lc.PADDING # Advance current_x past the text and its trailing padding

    # --- Elements from Right to Left for Sizing ---
    right_terminator_width = lc.BAR_HEIGHT
    
    # Calculate total width needed for all buttons and their inter-paddings
    button_texts = ["CLEAR", "RELATIVE", "CLOCK"]
    button_colors = [lc.COLOR_BUTTON_CLEAR, lc.COLOR_BUTTON_RELATIVE, lc.COLOR_BUTTON_CLOCK]
    button_details = []
    
    required_width_for_all_buttons_and_spacing = 0
    for i, btn_text in enumerate(button_texts):
        btn_w, _ = text_size(draw, btn_text, lc.BODY_FONT)
        button_render_width = btn_w + (2 * lc.BUTTON_PADDING_X)
        button_details.append({
            'text': btn_text, 
            'width': button_render_width, 
            'color': button_colors[i]
        })
        required_width_for_all_buttons_and_spacing += button_render_width
        if i < len(button_texts) - 1: # Add inter-button padding
            required_width_for_all_buttons_and_spacing += lc.PADDING

    # Determine the starting X position for the button group (aligning from the right)
    # Space before right terminator: lc.PADDING
    # Space before button group (between fill bar and first button): lc.PADDING
    buttons_group_start_x = (screen_width - lc.PADDING - right_terminator_width - lc.PADDING -
                             required_width_for_all_buttons_and_spacing)

    # --- Draw Fill Bar ---
    # Fill bar is between 'current_x' (after MQTT STREAM text) and 'buttons_group_start_x'
    fill_bar_start_x = current_x
    # Space between fill bar and first button is lc.PADDING
    fill_bar_end_x = buttons_group_start_x - lc.PADDING 
    fill_bar_width = fill_bar_end_x - fill_bar_start_x

    if fill_bar_width > 0:
        draw_lcars_shape(draw, fill_bar_start_x, BOTTOM_BAR_Y, fill_bar_width, lc.BAR_HEIGHT, 0, lc.COLOR_BARS, debug_draw_bbox=debug_layout_enabled)

    # --- Draw Buttons ---
    # Only draw buttons if the calculated start position for the group is sensible
    # (i.e., doesn't overlap with elements to its left like the MQTT STREAM text area)
    actual_button_draw_x = buttons_group_start_x
    if actual_button_draw_x >= current_x : # Check if there's space for buttons after MQTT text and potential fill bar
        for i, detail in enumerate(button_details):
            # This check ensures we don't try to draw buttons if the group itself wouldn't fit.
            # Individual button fitting within the group space is implicitly handled by prior width calculation.
            draw_lcars_shape(draw, actual_button_draw_x, BOTTOM_BAR_Y, detail['width'], lc.BAR_HEIGHT, 0, detail['color'], debug_draw_bbox=debug_layout_enabled)
            draw_text_in_rect(draw, detail['text'], lc.BODY_FONT,
                              actual_button_draw_x, BOTTOM_BAR_Y, detail['width'], lc.BAR_HEIGHT,
                              lc.TEXT_COLOR_BUTTON_LABEL, align="right", padding_x=lc.BUTTON_PADDING_X,
                              debug_draw_bbox=debug_layout_enabled) # Pass debug flag
            actual_button_draw_x += detail['width']
            if i < len(button_details) - 1:
                actual_button_draw_x += lc.PADDING
    else:
        # Not enough space for the button group, they won't be drawn.
        # The fill_bar might have expanded to fill the remaining space up to the right terminator's padding.
        # If fill_bar_width was also <=0, then it's a very narrow screen.
        pass


    # --- Draw Right Terminator ---
    # Position is fixed from the right edge of the screen
    final_right_terminator_x = screen_width - lc.PADDING - right_terminator_width
    # Check if it fits at all (e.g. screen isn't too narrow for PADDING + width + PADDING)
    if final_right_terminator_x >= lc.PADDING :
        draw_lcars_shape(draw, final_right_terminator_x, BOTTOM_BAR_Y, right_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, right_round=True, debug_draw_bbox=debug_layout_enabled)
