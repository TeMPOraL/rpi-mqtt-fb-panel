from PIL import ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Pillow helpers compatible with >=10 & <10
# ---------------------------------------------------------------------------
def text_size(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.ImageFont):
    """Return (w,h) for *txt* regardless of Pillow version."""
    if hasattr(draw, "textbbox"): # Pillow >= 6.2.0 for textbbox, >= 8.0.0 for textlength
        # textbbox((x,y), text, font) returns (left, top, right, bottom)
        # For size, we don't care about the anchor (x,y) so (0,0) is fine.
        bbox = draw.textbbox((0,0), txt, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Fallback for older Pillow versions (before textbbox)
    return draw.textsize(txt, font=font) # Deprecated in Pillow 10.0.0

# ---------------------------------------------------------------------------
# LCARS Drawing Helpers
# ---------------------------------------------------------------------------
import lcars_constants as lc # For debug colors

def draw_lcars_shape(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, radius: int,
                     color_bg, left_round: bool = False, right_round: bool = False,
                     debug_draw_bbox: bool = False):
    """
    Draws an LCARS-style shape (rectangle with optional rounded ends).
    Radius is typically h // 2 for semi-circular ends.
    If debug_draw_bbox is True, draws a 1px green bounding box.
    """
    if radius < 0: radius = 0 # Ensure radius is not negative

    # If width or height is less than 2*radius, rounding might not be possible or look good.
    # Adjust radius if it's too large for the dimensions.
    if (left_round or right_round) and w < 2 * radius : radius = w // 2
    if (left_round or right_round) and h < 2 * radius : radius = h // 2 # Though typically radius is h//2

    # Ensure radius does not exceed half the smaller dimension if both ends are rounded
    if left_round and right_round:
        max_radius = min(w / 2, h / 2)
        if radius > max_radius:
            radius = int(max_radius)
    elif left_round or right_round: # Single rounded end
        max_radius = h / 2 # Typically radius is based on height for side terminators
        if radius > max_radius:
            radius = int(max_radius)


    if left_round and right_round: # Pill shape
        if w > 2 * radius and h > 0: # Need width to draw the central rectangle
            draw.rectangle((x + radius, y, x + w - radius, y + h), fill=color_bg)
            # Left semi-circle
            draw.pieslice((x, y, x + 2 * radius, y + h), 90, 270, fill=color_bg)
            # Right semi-circle
            draw.pieslice((x + w - 2 * radius, y, x + w, y + h), -90, 90, fill=color_bg)
        elif w > 0 and h > 0: # Not enough width for distinct pill, draw ellipse or small rect
            draw.ellipse((x,y, x+w, y+h), fill=color_bg)

    elif left_round: # (] shape (rounded left)
        if w > radius and h > 0: # Need some width for the rectangular part
            draw.rectangle((x + radius, y, x + w, y + h), fill=color_bg)
            draw.pieslice((x, y, x + 2 * radius, y + h), 90, 270, fill=color_bg)
        elif w > 0 and h > 0: # Not enough width, draw a semi-circle or small rect
            # This case might need specific handling if w < radius
            draw.rectangle((x,y, x+w, y+h), fill=color_bg) # Fallback to simple rect

    elif right_round: # [) shape (rounded right)
        if w > radius and h > 0:
            draw.rectangle((x, y, x + w - radius, y + h), fill=color_bg)
            draw.pieslice((x + w - 2 * radius, y, x + w, y + h), -90, 90, fill=color_bg)
        elif w > 0 and h > 0:
            draw.rectangle((x,y, x+w, y+h), fill=color_bg) # Fallback

    else: # [] shape (simple rectangle)
        if w > 0 and h > 0:
            draw.rectangle((x, y, x + w, y + h), fill=color_bg)

    if debug_draw_bbox and w > 0 and h > 0:
        draw.rectangle((x, y, x + w -1 , y + h - 1), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)

def draw_text_in_rect(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
                      rect_x: int, rect_y: int, rect_w: int, rect_h: int,
                      text_color, align: str = "center", padding_x: int = 0, # Default padding_x to 0
                      debug_draw_bbox: bool = False):
    """
    Draws text within a given rectangle, with alignment.
    If debug_draw_bbox is True, draws a 1px green bounding box around the rect.
    """
    if not text or rect_w <= 0 or rect_h <= 0:
        return # Nothing to draw or no space

    text_w, text_h = text_size(draw, text, font=font)
    
    # Calculate text X position based on alignment
    if align == "center":
        text_x_offset = (rect_w - text_w) // 2
    elif align == "left":
        text_x_offset = padding_x
    elif align == "right":
        text_x_offset = rect_w - text_w - padding_x
    else: # default to center
        text_x_offset = (rect_w - text_w) // 2

    # Basic horizontal clipping: if text is wider than available space (minus padding)
    # and not centered, it might overflow. For now, we don't truncate here.
    # The caller should ensure text fits or handle truncation.

    text_x = rect_x + text_x_offset # This text_x is for the left edge, not used directly by anchor below

    # Calculate text Y position for a baseline anchor.
    # The goal is to center the ascent part of the font within the given rect_h,
    # allowing descenders to hang below if necessary.
    # font.getmetrics() returns (ascent, descent). Ascent is height above baseline.
    current_font_ascent, _ = font.getmetrics()
    
    # The y-coordinate for a baseline anchor ("ls", "ms", "rs") is the y of the baseline.
    # To center the ascent part (height `current_font_ascent`) within `rect_h`:
    # The top of the ascent part would be at `rect_y + (rect_h - current_font_ascent) // 2`.
    # The baseline is `current_font_ascent` pixels below that.
    # So, y_baseline = rect_y + (rect_h - current_font_ascent) // 2 + current_font_ascent
    # This simplifies to:
    y_coord_for_baseline_anchor = rect_y + (rect_h + current_font_ascent) // 2

    # Determine horizontal anchor character and X coordinate for that anchor point.
    # x_coord_for_anchor is recalculated based on alignment for the specific anchor point.
    # We need to recalculate x_coord_for_anchor based on the desired anchor.
    if align == "center":
        anchor_char_h = "m"  # Middle
        x_coord_for_anchor = rect_x + rect_w // 2
    elif align == "left":
        anchor_char_h = "l"  # Left
        x_coord_for_anchor = rect_x + padding_x
    elif align == "right":
        anchor_char_h = "r"  # Right
        # For right anchor, x_coord is rect_x + rect_w - padding_x (right edge of padded rect)
        x_coord_for_anchor = rect_x + rect_w - padding_x
    else:  # Default to center
        anchor_char_h = "m"
        x_coord_for_anchor = rect_x + rect_w // 2
    
    final_anchor = f"{anchor_char_h}s"  # e.g., "ls", "ms", "rs" (s for baseline)

    draw.text((x_coord_for_anchor, y_coord_for_baseline_anchor), text, font=font, fill=text_color, anchor=final_anchor)

    if debug_draw_bbox:
        draw.rectangle((rect_x, rect_y, rect_x + rect_w -1, rect_y + rect_h -1), outline=lc.DEBUG_BOUNDING_BOX_UI_ELEMENT, width=1)
