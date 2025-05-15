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
# BAR_HEIGHT is defined as the exact pixel height of an uppercase character from TITLE_FONT.
# This ensures bars snugly fit the height of title text like "EVENT LOG".
# We use getmask("M").size[1] to get the actual pixel height of a representative uppercase character.
# An ImageDraw instance is not needed for font.getmask().
try:
    # Get the actual pixel height of a representative uppercase character.
    # "M" is a common choice. Using "A" or any other non-descending uppercase char would also work.
    actual_title_text_height = TITLE_FONT.getmask("M").size[1]
    if actual_title_text_height <= 0: # Fallback if getmask returns non-positive height
        print("Warning: Font getmask returned non-positive height, using nominal size.", flush=True)
        actual_title_text_height = TITLE_FONT.size # Fallback to nominal size
except AttributeError:
    # Fallback for older Pillow versions or font types that might not have getmask directly
    # or if TITLE_FONT is not a TrueType/OpenType font.
    # Using getmetrics (ascent + descent) is a good fallback for TrueType.
    print("Warning: TITLE_FONT.getmask failed, attempting getmetrics.", flush=True)
    try:
        ascent, descent = TITLE_FONT.getmetrics()
        actual_title_text_height = ascent + descent
    except AttributeError:
        print("Warning: TITLE_FONT.getmetrics failed, using nominal size.", flush=True)
        actual_title_text_height = TITLE_FONT.size # Fallback to nominal size

BAR_HEIGHT = actual_title_text_height
CORNER_RADIUS = BAR_HEIGHT // 2
