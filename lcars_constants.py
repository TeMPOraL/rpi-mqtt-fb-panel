import os
from PIL import ImageFont, ImageColor

# Helper function to convert a color string to an RGB tuple.
# Supports various formats like hex (#RRGGBB), color names (e.g., "red"),
# rgb(R,G,B), hsl(H,S,L), etc., thanks to PIL.ImageColor.getrgb().
def Color(color_string: str) -> tuple[int, int, int]:
    """Converts a color string (e.g., '#RRGGBB', 'red', 'rgb(255,0,0)') to an RGB tuple."""
    return ImageColor.getrgb(color_string)

# ---------------------------------------------------------------------------
# Display Configuration
# ---------------------------------------------------------------------------
ROTATE       = int(os.getenv("DISPLAY_ROTATE", 0))
BG_COLOUR    = Color("#000000")

# ---------------------------------------------------------------------------
# LCARS Color Palette (TNG/VOY inspired)
# References: https://www.thelcars.com/colors.php
# ---------------------------------------------------------------------------
LCARS_ORANGE = Color("#FF9D00")      # Main interactive elements, bars
LCARS_BLUE = Color("#9BA2FF")        # Secondary elements, some buttons
LCARS_YELLOW = Color("#FFCB5F")       # Accent elements, some buttons
LCARS_RED_DARK = Color("#D47065")    # Warning/Alert buttons or accents
LCARS_BEIGE = Color("#FFCC99")       # Often used for text or backgrounds in some schemes
LCARS_PURPLE_LIGHT = Color("#CC99FF") # Body text, info messages
LCARS_CYAN = Color("#66CCFF")        # Control messages or other special info


# ---------------------------------------------------------------------------
# Default Text Colors
# ---------------------------------------------------------------------------
TEXT_COLOR_TITLE = LCARS_ORANGE
TEXT_COLOR_BODY = LCARS_PURPLE_LIGHT
TEXT_COLOR_BUTTON_LABEL = Color("#000000")
TEXT_COLOR_HIGHLIGHT = Color("#FFFFFF")


# ---------------------------------------------------------------------------
# Specific UI Element Colors
# ---------------------------------------------------------------------------
COLOR_BARS = LCARS_ORANGE
COLOR_BUTTON_CLEAR = LCARS_RED_DARK
COLOR_BUTTON_RELATIVE = LCARS_BLUE
COLOR_BUTTON_CLOCK = LCARS_YELLOW

# ---------------------------------------------------------------------------
# Debug Colors
# ---------------------------------------------------------------------------
DEBUG_BOUNDING_BOX_UI_ELEMENT = Color("#00FF00")
DEBUG_BOUNDING_BOX_MESSAGE_COLUMN = Color("#FF00FF")
DEBUG_MESSAGE_WRAP_LINE_COLOR = Color("#0000FF")

PROBE_COLOUR = Color("#FF00FF")

# ---------------------------------------------------------------------------
# Fonts
# NOTE: references a proper LCARS font that's (apparently) free for personal use.
# Not distributing it with this project. Alternatives include Antionio. Or just
# web-search for something if you don't have this one.
# Font path can be overridden by LCARS_FONT_PATH environment variable.
# ---------------------------------------------------------------------------
LCARS_FONT_PATH = os.getenv("LCARS_FONT_PATH")

# Default font paths if LCARS_FONT_PATH is not set or font at path not found
DEFAULT_LCARS_FONT_PATH = "/usr/share/fonts/truetype/dejavu/Swiss-911-Ultra-Compressed-BT-Regular.ttf"
FALLBACK_FONT_PATH = "DejaVuSans.ttf"

try:
    font_path_to_try = LCARS_FONT_PATH if LCARS_FONT_PATH else DEFAULT_LCARS_FONT_PATH
    TITLE_FONT   = ImageFont.truetype(font_path_to_try, 34)
    BODY_FONT    = ImageFont.truetype(font_path_to_try, 28)
    if LCARS_FONT_PATH and not os.path.exists(LCARS_FONT_PATH):
        print(f"Warning: LCARS_FONT_PATH '{LCARS_FONT_PATH}' not found. Trying default.", flush=True)
        # This will re-raise IOError if default also fails, caught by outer except
        TITLE_FONT   = ImageFont.truetype(DEFAULT_LCARS_FONT_PATH, 34)
        BODY_FONT    = ImageFont.truetype(DEFAULT_LCARS_FONT_PATH, 28)

except IOError:
    print(f"LCARS font not found at '{LCARS_FONT_PATH or DEFAULT_LCARS_FONT_PATH}'. Falling back to '{FALLBACK_FONT_PATH}'.", flush=True)
    try:
        TITLE_FONT = ImageFont.truetype(FALLBACK_FONT_PATH, 34)
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

# BAR_HEIGHT depends on TITLE_FONT.
# Ensure TITLE_FONT is loaded before this calculation.
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
