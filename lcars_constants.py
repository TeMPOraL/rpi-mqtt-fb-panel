import os
from PIL import ImageFont

# ---------------------------------------------------------------------------
# Display Configuration
# ---------------------------------------------------------------------------
ROTATE       = int(os.getenv("DISPLAY_ROTATE", 0)) # 0 / 90 / 180 / 270
BG_COLOUR    = (0, 0, 0) # Black

# ---------------------------------------------------------------------------
# LCARS Color Palette (TNG/VOY inspired)
# References: https://www.thelcars.com/colors.php
# ---------------------------------------------------------------------------
LCARS_ORANGE = (255, 157, 0)      # Main interactive elements, bars (#FF9D00 / TNG: #FF8800)
LCARS_BLUE = (155, 162, 255)        # Secondary elements, some buttons (#9BA2FF)
LCARS_YELLOW = (255, 203, 95)       # Accent elements, some buttons (#FFCB5F)
LCARS_RED_DARK = (212, 112, 101)    # Warning/Alert buttons or accents (#D47065)
LCARS_BEIGE = (255, 204, 153)       # Often used for text or backgrounds in some schemes (#FFCC99)
LCARS_PURPLE_LIGHT = (204, 153, 255) # Body text, info messages (#CC99FF)

# ---------------------------------------------------------------------------
# Text Colors
# ---------------------------------------------------------------------------
TEXT_COLOR_TITLE = LCARS_ORANGE
TEXT_COLOR_BODY = LCARS_PURPLE_LIGHT
TEXT_COLOR_BUTTON_LABEL = (0, 0, 0) # Black
TEXT_COLOR_HIGHLIGHT = (255, 255, 255) # White

# ---------------------------------------------------------------------------
# Specific UI Element Colors
# ---------------------------------------------------------------------------
COLOR_BARS = LCARS_ORANGE
COLOR_BUTTON_CLEAR = LCARS_RED_DARK
COLOR_BUTTON_RELATIVE = LCARS_BLUE
COLOR_BUTTON_CLOCK = LCARS_YELLOW

PROBE_COLOUR = (255, 0, 255) # Magenta for probe

# ---------------------------------------------------------------------------
# Fonts
# NOTE: references a proper LCARS font that's (apparently) free for personal use.
# Not distributing it with this project. Alternatives include Antionio. Or just
# web-search for something if you don't have this one.
# ---------------------------------------------------------------------------
try:
    TITLE_FONT   = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf", 34)
    BODY_FONT    = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf", 28)
except IOError:
    print("LCARS font not found, falling back to DejaVuSans.", flush=True)
    try:
        TITLE_FONT = ImageFont.truetype("DejaVuSans.ttf", 34)
        BODY_FONT = ImageFont.truetype("DejaVuSans.ttf", 28)
    except IOError:
        print("DejaVuSans.ttf not found, using default PIL font.", flush=True)
        TITLE_FONT = ImageFont.load_default()
        BODY_FONT = ImageFont.load_default()

# ---------------------------------------------------------------------------
# UI Dimensions
# ---------------------------------------------------------------------------
PADDING = 5  # General padding
BUTTON_PADDING_X = 10 # Horizontal padding inside buttons

# BAR_HEIGHT depends on TITLE_FONT.size and PADDING
# Ensure TITLE_FONT is loaded before this calculation
# Get font size. For TrueType fonts, size is roughly ascent + descent.
# Using .size attribute which is the requested point size.
# A more accurate height might be font.getbbox("A")[3] - font.getbbox("A")[1] or font.getmetrics()
# For simplicity, TITLE_FONT.size is used as an approximation of text height.
title_font_nominal_height = TITLE_FONT.size # Using nominal size as proxy for actual text height for bar calculation
# User wants bar height reduced by ~30% from a conceptual height that included padding.
conceptual_padded_height = title_font_nominal_height + PADDING * 2
# The user wants the bar height to be a percentage of this conceptual_padded_height.
# The 0.5 factor is from user's current file.
# If this makes the bar shorter than the font, the text will be centered in it,
# potentially appearing shifted/clipped, which achieves "taking more vertical space relative to bar height".
BAR_HEIGHT = int(conceptual_padded_height * 0.5)

# Ensure BAR_HEIGHT is at least a minimal positive value to prevent drawing errors.
BAR_HEIGHT = max(1, BAR_HEIGHT) # If scaling makes it too small or zero
CORNER_RADIUS = BAR_HEIGHT // 2
