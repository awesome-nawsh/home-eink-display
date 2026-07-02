"""Shared rendering primitives: fonts, the Material Design Icon glyph table,
the e-ink image-buffer manager, and generic icon-drawing helpers used by
every screen renderer.
"""
import os
import logging
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from config import picdir, SCREEN_WIDTH, SCREEN_HEIGHT, DISPLAY_FONT


# ============================================================================
# FONT MANAGEMENT
# ============================================================================
# The display typeface is chosen via DISPLAY_FONT in .env (web panel:
# "Display & Fonts"). Each entry maps a friendly name to a
# (regular, bold) file pair under pic/. The bundled non-Atkinson families
# are OFL-licensed; each ships with its OFL.txt alongside the files.
FONT_REGISTRY = {
    'Atkinson Regular': ('AtkinsonHyperlegibleNext-Regular.otf',
                         'AtkinsonHyperlegibleNext-Bold.otf'),
    'Atkinson Medium': ('Atkinson Hyperlegible Next/AtkinsonHyperlegibleNext-Medium.otf',
                        'Atkinson Hyperlegible Next/AtkinsonHyperlegibleNext-ExtraBold.otf'),
    'Atkinson SemiBold': ('Atkinson Hyperlegible Next/AtkinsonHyperlegibleNext-SemiBold.otf',
                          'Atkinson Hyperlegible Next/AtkinsonHyperlegibleNext-ExtraBold.otf'),
    'Inter': ('Inter/Inter-Regular.ttf', 'Inter/Inter-Bold.ttf'),
    'IBM Plex Sans': ('IBMPlexSans/IBMPlexSans-Regular.ttf',
                      'IBMPlexSans/IBMPlexSans-Bold.ttf'),
    'Noto Sans': ('NotoSans/NotoSans-Regular.ttf', 'NotoSans/NotoSans-Bold.ttf'),
    # E-ink-oriented faces: Bitter (slab serif designed for e-readers),
    # Literata (Google Play Books' e-reading serif), Lexend (legibility-
    # research sans), Fira Sans (designed for low-res screens).
    'Bitter': ('Bitter/Bitter-Regular.ttf', 'Bitter/Bitter-Bold.ttf'),
    'Literata': ('Literata/Literata-Regular.ttf', 'Literata/Literata-Bold.ttf'),
    'Lexend': ('Lexend/Lexend-Regular.ttf', 'Lexend/Lexend-Bold.ttf'),
    'Fira Sans': ('FiraSans/FiraSans-Regular.ttf', 'FiraSans/FiraSans-Bold.ttf'),
}
_FALLBACK_FONT_NAME = 'Atkinson Regular'


def resolve_font_pair(name):
    """Registry name -> (regular_path, bold_path) absolute paths, falling
    back to Atkinson Regular (with a warning) on an unknown name or missing
    file — a typo'd DISPLAY_FONT must never take the display down."""
    files = FONT_REGISTRY.get(name)
    if files is None:
        logging.warning(f"DISPLAY_FONT '{name}' not in the font registry - using {_FALLBACK_FONT_NAME}")
        files = FONT_REGISTRY[_FALLBACK_FONT_NAME]
    paths = tuple(os.path.join(picdir, f) for f in files)
    if not all(os.path.exists(p) for p in paths):
        logging.warning(f"Font file(s) missing for '{name}' - using {_FALLBACK_FONT_NAME}")
        paths = tuple(os.path.join(picdir, f) for f in FONT_REGISTRY[_FALLBACK_FONT_NAME])
    return paths


_regular_font_path, _bold_font_path = resolve_font_pair(DISPLAY_FONT)


@lru_cache(maxsize=8)
def get_font(size, font_name=None):
    """Cache fonts to avoid reloading from disk. `font_name` (a path under
    pic/) overrides the DISPLAY_FONT-selected regular face."""
    path = os.path.join(picdir, font_name) if font_name else _regular_font_path
    return ImageFont.truetype(path, size)

@lru_cache(maxsize=4)
def get_font_bold(size):
    """Get the bold face of the DISPLAY_FONT-selected family."""
    try:
        return ImageFont.truetype(_bold_font_path, size)
    except OSError:
        logging.warning("Bold font not found, using regular")
        return get_font(size)

@lru_cache(maxsize=4)
def get_icon_font(size):
    """Get Material Design Icons font for rendering icons."""
    try:
        return ImageFont.truetype(os.path.join(picdir, 'materialdesignicons-webfont.ttf'), size)
    except OSError:
        logging.warning("MDI font not found, using regular font as fallback")
        return get_font(size)

# Material Design Icon Unicode characters (MDI v7.4.47)
class MDI:
    """Material Design Icons Unicode characters for version 7.4.47."""
    BUS = "\U000F010B"
    BUS_MARKER = "\U000F1212"
    BUS_STOP = "\U000F1012"
    BUS_SIDE = "\U000F0710"
    TRAIN = "\U000F04DE"
    TRAIN_VARIANT = "\U000F08C7"
    TRAIN_CAR = "\U000F0BD8"
    SUBWAY = "\U000F06AC"
    SUBWAY_VARIANT = "\U000F0D72"
    ALERT = "\U000F0026"
    ALERT_CIRCLE = "\U000F0027"
    ALERT_CIRCLE_OUTLINE = "\U000F05D6"
    CHECK_CIRCLE = "\U000F05E0"
    CHECK_CIRCLE_OUTLINE = "\U000F05E1"
    CLOCK = "\U000F0954"
    CLOCK_OUTLINE = "\U000F0150"
    UPDATE = "\U000F06A6"
    REFRESH = "\U000F0450"
    WIFI = "\U000F05A9"
    SLEEP = "\U000F098C"
    ACCOUNT_MULTIPLE = "\U000F0004"
    SPEEDOMETER = "\U000F063E"
    HOME = "\U000F02DC"
    HOME_AUTOMATION = "\U000F07D0"
    INFORMATION = "\U000F02FC"
    INFORMATION_OUTLINE = "\U000F02FD"
    # Weather icons
    WEATHER_SUNNY = "\U000F0599"
    WEATHER_CLOUDY = "\U000F0590"
    WEATHER_RAINY = "\U000F0597"
    WEATHER_PARTLY_CLOUDY = "\U000F0595"
    WEATHER_NIGHT = "\U000F0594"
    THERMOMETER = "\U000F0E02"
    WATER_PERCENT = "\U000F058E"
    LEAF = "\U000F032A"                     # air quality (PSI) marker
    # Journey/navigation icons
    MAP_MARKER_DISTANCE = "\U000F08F0"
    TIMER = "\U000F13B3"
    NAVIGATION = "\U000F0423"
    # Load/Capacity icons (see BUS_LOAD_MAP_ICON below)
    SEAT_PASSENGER = "\U000F0E2F"           # mdi-seat-passenger (F0E2F)
    HUMAN_MALE = "\U000F0649"               # mdi-human-male (F0649)
    MINUS_CIRCLE_OUTLINE = "\U000F0376"     # mdi-minus-circle-outline (F0376)

BUS_LOAD_MAP_ICON = {
    'SEA': MDI.SEAT_PASSENGER,      # Seats available
    'SDA': MDI.HUMAN_MALE,           # Standing available
    'LSD': MDI.MINUS_CIRCLE_OUTLINE  # Limited standing
}

# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================
class DisplayManager:
    """Manages image buffers for the e-ink display."""
    def __init__(self, epd):
        if epd.width != SCREEN_WIDTH or epd.height != SCREEN_HEIGHT:
            raise ValueError(
                f"Panel reports {epd.width}x{epd.height} but SCREEN_WIDTH/SCREEN_HEIGHT "
                f"are set to {SCREEN_WIDTH}x{SCREEN_HEIGHT}. Draw functions use the "
                f"SCREEN_WIDTH/SCREEN_HEIGHT constants directly, not the panel's reported "
                f"size, so update those constants (config.py) to match the driver in use."
            )
        self.epd = epd
        self.black_image = Image.new('1', (epd.width, epd.height), 255)
        self.red_image = Image.new('1', (epd.width, epd.height), 255)

    def clear_images(self):
        """Clear both image buffers and return draw objects."""
        self.black_image.paste(255, (0, 0, self.epd.width, self.epd.height))
        self.red_image.paste(255, (0, 0, self.epd.width, self.epd.height))
        return ImageDraw.Draw(self.black_image), ImageDraw.Draw(self.red_image)

    def display(self):
        """Update the e-ink display with current image buffers."""
        self.epd.display(self.epd.getbuffer(self.black_image),
                        self.epd.getbuffer(self.red_image))

def draw_mdi_icon(draw, x, y, icon_char, size=50, color=0, anchor=None):
    """Draw a Material Design Icon at the specified position.

    `anchor` is passed straight through to PIL's text anchor system (e.g.
    "mm" to center the icon on (x, y)) — optional and defaults to PIL's
    normal top-left placement, so existing call sites are unaffected.
    """
    icon_font = get_icon_font(size)
    draw.text((x, y), icon_char, font=icon_font, fill=color, anchor=anchor)

def get_weather_icon(condition):
    """Map weather condition to MDI icon."""
    condition_lower = condition.lower() if condition else ""

    if 'clear' in condition_lower or 'sunny' in condition_lower:
        return MDI.WEATHER_SUNNY
    elif 'rain' in condition_lower or 'rainy' in condition_lower:
        return MDI.WEATHER_RAINY
    elif 'cloud' in condition_lower:
        if 'partly' in condition_lower or 'partial' in condition_lower:
            return MDI.WEATHER_PARTLY_CLOUDY
        return MDI.WEATHER_CLOUDY
    elif 'night' in condition_lower:
        return MDI.WEATHER_NIGHT
    else:
        return MDI.WEATHER_PARTLY_CLOUDY
