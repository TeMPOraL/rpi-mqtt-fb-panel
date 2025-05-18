from functools import lru_cache
from PIL import ImageFont

@lru_cache(maxsize=256)
def get_font(font_path: str, size: int):
    """
    Cached loader.  Returns a Pillow ImageFont instance for the
    given (font_path, size) pair, avoiding repeated disk I/O.
    """
    return ImageFont.truetype(font_path, size)
