from PIL import ImageDraw, ImageFont
import lcars_constants as lc
from lcars_drawing_utils import draw_lcars_shape, draw_text_in_rect, text_size

def render_top_bar(draw: ImageDraw.ImageDraw, screen_width: int):
    """Renders the top LCARS bar with 'EVENT LOG' title."""
    # Left Terminator (])
    left_terminator_width = lc.BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, lc.PADDING, lc.PADDING, left_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, left_round=True)

    # Right Terminator [)
    right_terminator_width = lc.BAR_HEIGHT # Width of the terminator element
    draw_lcars_shape(draw, screen_width - lc.PADDING - right_terminator_width, lc.PADDING, right_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, right_round=True)

    # "EVENT LOG" Text and associated Bar Segment
    # The Left and Right Terminators are drawn by the code immediately preceding this block.
    # This section calculates the position for the "EVENT LOG" text, draws it,
    # and then draws a bar segment filling the space between the Left Terminator and the text.

    event_log_text = "EVENT LOG"
    # text_size is imported from lcars_drawing_utils at the top of the file
    event_log_text_w, _ = text_size(draw, event_log_text, lc.TITLE_FONT) # Height not needed for baseline anchor

    # Determine X position for "EVENT LOG" text (left edge).
    # The right edge of the text should be lc.PADDING to the left of the Right Terminator's starting X.
    text_x_coordinate = (screen_width - lc.PADDING - lc.BAR_HEIGHT) - lc.PADDING - event_log_text_w
    
    # Calculate Y position for the baseline of "EVENT LOG" text.
    # For TITLE_FONT within a BAR_HEIGHT sized to it, the baseline is at the bottom of the bar.
    # lc.PADDING is the Y offset for the top bar itself.
    event_log_baseline_y = lc.PADDING + lc.BAR_HEIGHT
    
    # Draw the "EVENT LOG" text directly on the background, using "ls" (left-baseline) anchor.
    # text_x_coordinate is the calculated left edge for the text.
    draw.text((text_x_coordinate, event_log_baseline_y), event_log_text, font=lc.TITLE_FONT, fill=lc.TEXT_COLOR_TITLE, anchor="ls")

    # Draw the Main Bar Segment.
    # It starts after the Left Terminator and ends before the "EVENT LOG" text.
    # The Left Terminator ends at: lc.PADDING + left_terminator_width
    # Note: left_terminator_width is defined above and is equal to lc.BAR_HEIGHT.
    bar_segment_start_x = lc.PADDING + lc.BAR_HEIGHT
    
    # The bar segment should end lc.PADDING to the left of where the "EVENT LOG" text starts.
    bar_segment_end_x = text_x_coordinate - lc.PADDING
    
    bar_segment_width = bar_segment_end_x - bar_segment_start_x

    if bar_segment_width > 0:
        # Draw the bar segment (no rounding for this piece, it's a simple rectangle).
        # It uses lc.PADDING as its Y coordinate and lc.BAR_HEIGHT as its height.
        draw_lcars_shape(draw, bar_segment_start_x, lc.PADDING, bar_segment_width, lc.BAR_HEIGHT, 0, lc.COLOR_BARS)

def render_bottom_bar(draw: ImageDraw.ImageDraw, screen_width: int, screen_height: int):
    """Renders the bottom LCARS bar with 'MQTT STREAM' label and buttons."""
    BOTTOM_BAR_Y = screen_height - lc.PADDING - lc.BAR_HEIGHT
    left_terminator_width = lc.BAR_HEIGHT # Same as top bar

    # Left Terminator (]) for bottom bar
    draw_lcars_shape(draw, lc.PADDING, BOTTOM_BAR_Y, left_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, left_round=True)

    # "MQTT STREAM" Label Bar Segment
    mqtt_stream_text = "MQTT STREAM"
    mqtt_stream_text_w, _ = text_size(draw, mqtt_stream_text, lc.TITLE_FONT)
    mqtt_stream_bar_w = mqtt_stream_text_w + 2 * lc.BUTTON_PADDING_X # Bar width includes padding for text
    mqtt_stream_bar_x = lc.PADDING + left_terminator_width

    # Draw "MQTT STREAM" text directly for precise baseline control.
    # For TITLE_FONT within a BAR_HEIGHT sized to it, the baseline is at the bottom of the bar.
    # Align: "center" means anchor "ms" (middle-baseline).
    # X-coordinate for "ms" anchor is the horizontal center of the bar segment.
    mqtt_stream_text_center_x = mqtt_stream_bar_x + mqtt_stream_bar_w // 2
    mqtt_stream_baseline_y = BOTTOM_BAR_Y + lc.BAR_HEIGHT
    
    draw.text((mqtt_stream_text_center_x, mqtt_stream_baseline_y), 
              mqtt_stream_text, 
              font=lc.TITLE_FONT, 
              fill=lc.TEXT_COLOR_TITLE, 
              anchor="ms")

    current_x_bottom_bar = mqtt_stream_bar_x + mqtt_stream_bar_w + lc.PADDING

    # Buttons: [CLEAR], [RELATIVE], [CLOCK]
    button_texts = ["CLEAR", "RELATIVE", "CLOCK"]
    button_colors = [lc.COLOR_BUTTON_CLEAR, lc.COLOR_BUTTON_RELATIVE, lc.COLOR_BUTTON_CLOCK]

    for i, btn_text in enumerate(button_texts):
        btn_w, _ = text_size(draw, btn_text, lc.BODY_FONT) # Use BODY_FONT for button labels
        button_total_width = btn_w + 2 * lc.BUTTON_PADDING_X

        # Ensure button doesn't overflow available space before drawing
        if current_x_bottom_bar + button_total_width < screen_width - lc.PADDING:
            draw_lcars_shape(draw, current_x_bottom_bar, BOTTOM_BAR_Y, button_total_width, lc.BAR_HEIGHT, 0, button_colors[i]) # Square buttons
            draw_text_in_rect(draw, btn_text, lc.BODY_FONT,
                              current_x_bottom_bar, BOTTOM_BAR_Y, button_total_width, lc.BAR_HEIGHT,
                              lc.TEXT_COLOR_BUTTON_LABEL, align="right")
            current_x_bottom_bar += button_total_width + lc.PADDING
        else:
            # Not enough space for this button, break or log
            break

    # Right Fill Bar [==)
    right_fill_bar_x = current_x_bottom_bar
    # The rightmost point for the fill bar is before the screen padding
    # It should not overlap with a potential right terminator if we had one here,
    # but the mockup is (] ... buttons ... [==)
    # So, it fills up to screen_width - PADDING
    right_fill_bar_w = screen_width - lc.PADDING - right_fill_bar_x

    if right_fill_bar_w > lc.CORNER_RADIUS : # Ensure there's enough space for the rounded end
        draw_lcars_shape(draw, right_fill_bar_x, BOTTOM_BAR_Y, right_fill_bar_w, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, right_round=True)
    elif right_fill_bar_w > 0: # If not enough for rounding, draw square if space permits
        draw_lcars_shape(draw, right_fill_bar_x, BOTTOM_BAR_Y, right_fill_bar_w, lc.BAR_HEIGHT, 0, lc.COLOR_BARS)
