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
    # It starts lc.PADDING after the Left Terminator and ends lc.PADDING before the "EVENT LOG" text.
    # Left Terminator: x=lc.PADDING, width=lc.BAR_HEIGHT. So it ends at lc.PADDING + lc.BAR_HEIGHT.
    bar_segment_start_x = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING # Add lc.PADDING gap
    
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
    # This bar segment contains the text and has its own internal padding (BUTTON_PADDING_X).
    mqtt_stream_bar_w = mqtt_stream_text_w + (2 * lc.BUTTON_PADDING_X)
    # The bar segment itself starts lc.PADDING after the left terminator.
    # Left Terminator: x=lc.PADDING, width=lc.BAR_HEIGHT. Ends at lc.PADDING + lc.BAR_HEIGHT.
    mqtt_stream_bar_x = lc.PADDING + lc.BAR_HEIGHT + lc.PADDING # Add lc.PADDING gap

    # Draw the bar segment for "MQTT STREAM" (square ends)
    draw_lcars_shape(draw, mqtt_stream_bar_x, BOTTOM_BAR_Y, mqtt_stream_bar_w, lc.BAR_HEIGHT, 0, lc.COLOR_BARS)

    # Draw "MQTT STREAM" text directly within its bar for precise baseline control.
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
                              lc.TEXT_COLOR_BUTTON_LABEL, align="right", padding_x=lc.BUTTON_PADDING_X)
            current_x_bottom_bar += button_total_width + lc.PADDING
        else:
            # Not enough space for this button, break or log
            break

    # Right side: Optional rectangular bar segment, then a distinct Right Terminator [)
    fill_bar_start_x = current_x_bottom_bar # This X already includes lc.PADDING from the last button

    # Calculate position and width for the Right Terminator
    right_terminator_width = lc.BAR_HEIGHT # Standard width for terminators
    right_terminator_x = screen_width - lc.PADDING - right_terminator_width

    # Calculate width for the fill bar segment that sits before the right terminator
    # It ends lc.PADDING before the right_terminator_x
    fill_bar_end_x = right_terminator_x - lc.PADDING
    fill_bar_width = fill_bar_end_x - fill_bar_start_x

    # Draw the rectangular fill bar segment if there's space
    if fill_bar_width > 0:
        draw_lcars_shape(draw, fill_bar_start_x, BOTTOM_BAR_Y, fill_bar_width, lc.BAR_HEIGHT, 0, lc.COLOR_BARS)
    
    # Draw the Right Terminator [)
    # Ensure there's actually space for the terminator itself before drawing
    if right_terminator_x >= fill_bar_start_x or fill_bar_width <=0 : # if fill bar was not drawn or terminator is to its right
         if screen_width - lc.PADDING - right_terminator_width >= lc.PADDING : # Check if it fits on screen at all
            draw_lcars_shape(draw, right_terminator_x, BOTTOM_BAR_Y, right_terminator_width, lc.BAR_HEIGHT, lc.CORNER_RADIUS, lc.COLOR_BARS, right_round=True)
