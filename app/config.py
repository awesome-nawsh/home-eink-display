"""Environment configuration, layout constants, and startup validation.

Every other module imports from here (typically via ``from config import *``)
rather than reading os.getenv() directly, so there is exactly one place that
owns the process's configuration. Values are loaded once at import time and
generally require a process restart to pick up changes — except the small
allowlist in DYNAMIC_CONFIG_VARS (currently just FORCE_SCREEN), which
reload_dynamic_vars() can refresh live. See main.py's loop for how that's
triggered (MQTT config_reload topic + a .env mtime-poll backstop). Retrofitting
every variable to be dynamically reloadable would mean every read site across
the codebase doing a dotted config.SOMEVAR lookup instead of a bare imported
name — a large, invasive rewrite not worth it for variables nobody's asked to
change without a restart (see design.md).
"""
import sys
import os
import threading
import logging
from datetime import datetime
from dotenv import load_dotenv

from scheduler import SCREEN_NAMES  # FORCE_SCREEN validation below; scheduler.py has
                                     # no imports of its own, so this can't create a cycle.
from secrets_vault import get_or_create_key, decrypt_value

# Explicit path (rather than load_dotenv()'s implicit cwd-upward search) so
# reload_dynamic_vars() can re-read the exact same file later.
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), '.env')
load_dotenv(ENV_FILE_PATH)

# Setting up directories
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

# Configure logging based on environment variable
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Secrets-at-rest encryption key. Protects .env values viewed/shared/committed
# in isolation — NOT a defense against full filesystem access to this device,
# since the key must live on the same disk to be usable at process start.
SECRETS_KEY_PATH = os.getenv(
    'SECRETS_KEY_PATH',
    os.path.join(os.path.dirname(os.path.realpath(__file__)), '.encryption_key')
)
_secrets_key = get_or_create_key(SECRETS_KEY_PATH)

# ============================================================================
# CONSTANTS
# ============================================================================
BUS_LOAD_MAP_SIZE = {'SEA': 10, 'SDA': 50, 'LSD': 90}
BUS_LOAD_MAP_TEXT = {'SEA': 'Seats', 'SDA': 'Standing', 'LSD': 'Limited'}

# Physical panel dimensions — must match EPD_WIDTH/EPD_HEIGHT in
# lib/waveshare_epd/epd7in5b_V2.py. Every other layout constant below is
# either a fixed offset from the edges/each other or derived from these
# two values, so resizing the panel only means changing these two lines
# (DisplayManager checks the real hardware against these at startup and
# refuses to run if they've drifted apart).
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

# Display layout constants
COLUMN_WIDTH_RATIO = 0.5
COLUMN_OFFSET = int(SCREEN_WIDTH * COLUMN_WIDTH_RATIO)  # x boundary between the bus column and the train/weather column
BUS_BOX_HEIGHT = 60
BUS_BOX_WIDTH = 160
BUS_BOX_Y_OFFSET = 70  # y_start for draw_bus_section: 15px below the header divider at y=55
BUS_BOX_Y_SPACING = 105
BUS_NUMBER_FONT_SIZE = 32
LOAD_FONT_SIZE = 16
BOTTOM_FONT_SIZE = 14
BOTTOM_MARGIN = 35
TOP_MARGIN = 20
DIVIDER_WIDTH = 2
WEATHER_SECTION_HEIGHT = 140  # px reserved at the bottom of the right column for weather

# Standard font sizes (consolidated)
FONT_SMALL = 12
FONT_MEDIUM = 16
FONT_LARGE = 24
FONT_XLARGE = 32
FONT_TIMESTAMP = 18  # timestamp, journey-time line, boot "Booted:" text
FONT_SECTION = 20    # weather header (bold) / train body font size
FONT_HEADER = 28     # bold section title font size: bus/train headers, DEBUG MODE

# Header layout (shared by the boot screen, main view, and debug screen)
HEADER_ICON_X = 15
HEADER_ICON_Y = 5
HEADER_ICON_SIZE = 50
HEADER_DIVIDER_Y = 55  # y of the divider line under both column headers
HEADER_TEXT_Y = 18     # y of both column header titles ("Bus Stop" / "Train Status")
COLUMN_DIVIDER_TOP_Y = 60  # y where the center vertical divider starts (below the header row)
TRAIN_COLUMN_INDENT = 20   # x indent of the train column from the center divider

# Bus section layout
BUS_SECTION_X = 20        # left x for the bus number box and journey divider
BUS_BOX_TOP_GAP = 10      # gap between a row's y and its box_top
BUS_TIMES_X = 200         # x for the arrival-times text (also the load-text fallback x)
BUS_LOAD_ICON_X = 195
BUS_LOAD_TEXT_X = 213
BUS_LOAD_BAR_X1 = 150
BUS_LOAD_BAR_X2 = 170
JOURNEY_ICON_X = 25       # x for journey-related MDI icons (map-marker, timer)
JOURNEY_HEADER_GAP = 35   # vertical space reserved for the optional journey destination header
LOAD_TEXT_Y_NUDGE = 8     # vertical centering correction for the load text/bar
JOURNEY_Y_GAP = 8         # gap below a bus box before its journey-time line

# Train section layout
TRAIN_SECTION_Y_OFFSET = 70      # y_offset start for train content, below HEADER_DIVIDER_Y
TRAIN_LINE_SPACING = 32          # vertical spacing between most train status lines
TRAIN_LINE_SPACING_SMALL = 28    # tighter spacing before "expected."/"Alert:" lines
TRAIN_WRAP_WIDTH = 22            # textwrap width for station lists and alert content
TRAIN_STATION_LINE_SPACING = 24
TRAIN_ALERT_LINE_SPACING = 22
TRAIN_DISRUPTION_GAP = 15        # gap after each disruption block
ALERT_SECTION_GAP = 10           # gap before the "Alert:" divider line
ALERT_POST_DIVIDER_GAP = 15      # gap after the "Alert:" divider, before the icon/label

# Weather section layout
WEATHER_POST_DIVIDER_GAP = 15  # gap after the weather divider before the header
WEATHER_HEADER_GAP = 28        # gap after "Weather" header before the icon/temp row

# Screen edges
SCREEN_MARGIN = 10       # standard left/right margin for divider lines
TEXT_RIGHT_MARGIN = 15   # margin subtracted for right-aligned text (timestamp/date)

# Resilience / timing
HTTP_TIMEOUT_DEFAULT = 10
HTTP_TIMEOUT_LONG = 15
# (Stuck-loop protection is systemd's WatchdogSec in bus_display.service,
# pinged via health.sd_notify() — no in-process timeout constant needed.)

# Environment variables with defaults
API_KEY = decrypt_value(os.getenv('API_KEY'), _secrets_key)
BUS_API_URL = os.getenv('API_BUS_URL', 'Not Found - bus API url')
TRAIN_API_URL = os.getenv('API_TRAIN_URL', 'Not Found - train API url')
API_BUS_STOP_INFO_URL = os.getenv('API_BUS_STOP_INFO_URL', 'Not Found - bus stop API url')
HEADER_A = os.getenv('A_HEADER', 'Bus Stop')
BUS_STOP_CODE_A = os.getenv('BUS_STOP_CODE_A')

# Journey Time Configuration - Simplified with API
SHOW_JOURNEY_TIME = os.getenv('SHOW_JOURNEY_TIME', 'false').lower() == 'true'
BUS_SERVICES_TO_TRACK = [s.strip() for s in os.getenv('BUS_SERVICES_TO_TRACK', '').split(',') if s.strip()]
JOURNEY_DESTINATION = os.getenv('JOURNEY_DESTINATION', 'Destination')  # e.g., "School Name, Singapore" or "123 Main St"
JOURNEY_DESTINATION_SHORT = os.getenv('JOURNEY_DESTINATION_SHORT')  # Short name for display (optional)

# Routing API Configuration
ROUTING_API_PROVIDER = os.getenv('ROUTING_API_PROVIDER', 'onemap').lower()  # 'onemap' or 'google'
GOOGLE_MAPS_API_KEY = decrypt_value(os.getenv('GOOGLE_MAPS_API_KEY'), _secrets_key)  # Required if using Google
ONEMAP_API_KEY = decrypt_value(os.getenv('ONEMAP_API_KEY'), _secrets_key)  # Optional for OneMap

# Journey time cache (longer duration since routes don't change often)
JOURNEY_TIME_CACHE_DURATION = int(os.getenv('JOURNEY_TIME_CACHE_DURATION', '1800'))  # 30 minutes default

# Legacy wake/sleep hours — no longer read directly by main.py's loop (see
# scheduler.py), kept only as the migration-fallback input to
# default_schedule_from_env() when schedule_config.json is absent.
WAKE_HOUR = int(os.getenv('WAKE_HOUR', '7'))
SLEEP_HOUR = int(os.getenv('SLEEP_HOUR', '22'))
WAKE_INTERVAL = int(os.getenv('WAKE_INTERVAL', '30'))
SLEEP_INTERVAL = int(os.getenv('SLEEP_INTERVAL', '300'))
DEBUG_SKIP_TIME_CHECK = os.getenv('DEBUG_SKIP_TIME_CHECK', 'false').lower() == 'true'

# Four-screen scheduler (schedule_config.json) and day-type resolution
HOME_ASSISTANT_SCHOOL_DAY_ENTITY = os.getenv('HOME_ASSISTANT_SCHOOL_DAY_ENTITY', 'binary_sensor.school_day')
HOME_ASSISTANT_WORKDAY_ENTITY = os.getenv('HOME_ASSISTANT_WORKDAY_ENTITY', 'binary_sensor.workday_sensor')
DAY_TYPE_FALLBACK = os.getenv('DAY_TYPE_FALLBACK', 'work_day')
SCHEDULE_CONFIG_PATH = os.getenv(
    'SCHEDULE_CONFIG_PATH',
    os.path.join(os.path.dirname(os.path.realpath(__file__)), 'schedule_config.json')
)

# Testing override: force a specific screen regardless of schedule/day-type
# (one of scheduler.SCREEN_NAMES, or unset/empty for normal resolution).
# Intended for verifying a screen renders correctly on real hardware without
# waiting for its schedule window or day-type to naturally occur — not meant
# to be left set in production. This is the one variable in
# DYNAMIC_CONFIG_VARS: main.py reads it via a dotted config.FORCE_SCREEN
# lookup each loop tick (not a bare imported name) specifically so
# reload_dynamic_vars() can update it live, without a process restart.
def _resolve_force_screen(raw_value):
    """Pure. Validates a raw FORCE_SCREEN string against scheduler.SCREEN_NAMES.
    Returns the valid screen name, or None (unset/empty/invalid). Invalid
    values are logged and treated as unset rather than raising, so a typo
    in .env degrades to normal schedule resolution instead of crashing."""
    raw_value = (raw_value or '').strip()
    if not raw_value:
        return None
    if raw_value not in SCREEN_NAMES:
        logging.warning(
            f"FORCE_SCREEN={raw_value!r} is not a valid screen name "
            f"({', '.join(SCREEN_NAMES)}) - ignoring, using normal schedule resolution"
        )
        return None
    return raw_value


FORCE_SCREEN = _resolve_force_screen(os.getenv('FORCE_SCREEN', ''))

# Dynamic (no-restart) config reload — see module docstring. A small,
# deliberate allowlist, not "everything" — see design.md for why.
DYNAMIC_CONFIG_VARS = ('FORCE_SCREEN',)
config_reload_requested = threading.Event()


def reload_dynamic_vars():
    """Re-reads .env and refreshes DYNAMIC_CONFIG_VARS in place (mutates this
    module's own globals via `global`, so any dotted config.FORCE_SCREEN
    lookup elsewhere sees the update immediately). Triggered by main.py on
    the MQTT config_reload topic or a .env mtime change — see main.py's loop.
    """
    global FORCE_SCREEN
    load_dotenv(ENV_FILE_PATH, override=True)
    FORCE_SCREEN = _resolve_force_screen(os.getenv('FORCE_SCREEN', ''))
    logging.info(f"Dynamic config reloaded: FORCE_SCREEN={FORCE_SCREEN}")

# Boot-screen connectivity checklist
BOOT_CHECK_TIMEOUT = float(os.getenv('BOOT_CHECK_TIMEOUT', '3'))
INTERNET_CHECK_URL = os.getenv('INTERNET_CHECK_URL', 'https://www.google.com/generate_204')

# Home Assistant Configuration
HOME_ASSISTANT_API_URL = os.getenv('HOME_ASSISTANT_API_URL')
HOME_ASSISTANT_TOKEN = decrypt_value(os.getenv('HOME_ASSISTANT_TOKEN'), _secrets_key)
HOME_ASSISTANT_WEATHER_ENTITY = os.getenv('HOME_ASSISTANT_WEATHER_ENTITY', 'weather.home')
# HOME_ASSISTANT_DASHBOARD_URL is the ha_screen image source (renamed from
# "sleep screen" now that it's shown per its own schedule entry, not tied to
# WAKE_HOUR/SLEEP_HOUR). HOME_ASSISTANT_SLEEP_URL is read as a fallback so
# existing .env files deployed before this rename keep working.
HOME_ASSISTANT_DASHBOARD_URL = os.getenv('HOME_ASSISTANT_DASHBOARD_URL') or os.getenv('HOME_ASSISTANT_SLEEP_URL')
SLEEP_SCREEN_DASHBOARD = os.getenv('SLEEP_SCREEN_DASHBOARD')
SLEEP_SCREEN_EINK_MODE = os.getenv('SLEEP_SCREEN_EINK_MODE', '2')
SLEEP_SCREEN_ZOOM = os.getenv('SLEEP_SCREEN_ZOOM', '1')
SLEEP_SCREEN_FORMAT = os.getenv('SLEEP_SCREEN_FORMAT')
SLEEP_SCREEN_WAIT = os.getenv('SLEEP_SCREEN_WAIT', '5000')
SLEEP_SCREEN_THEME = os.getenv('SLEEP_SCREEN_THEME', 'Graphite E-ink Light')

# MQTT Configuration
MQTT_ENABLED = os.getenv('MQTT_ENABLED', 'false').lower() == 'true'
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = decrypt_value(os.getenv('MQTT_PASSWORD', ''), _secrets_key)
MQTT_TOPIC_REFRESH = os.getenv('MQTT_TOPIC_REFRESH', 'eink/display/refresh')
MQTT_TOPIC_STATUS = os.getenv('MQTT_TOPIC_STATUS', 'eink/display/status')
MQTT_TOPIC_CONFIG_RELOAD = os.getenv('MQTT_TOPIC_CONFIG_RELOAD', 'eink/display/config_reload')

# Cache duration
CACHE_DURATION = int(os.getenv('CACHE_DURATION', '20'))
WEATHER_CACHE_DURATION = int(os.getenv('WEATHER_CACHE_DURATION', '1800'))
# How long the bus/train fetchers may keep serving last-known-good data past
# its normal TTL while the LTA API is failing, before giving up and showing
# an explicit "data unavailable" error on screen instead. A genuinely empty
# API response (no buses running) is NOT an error and renders as blank.
STALE_DATA_MAX_AGE = int(os.getenv('STALE_DATA_MAX_AGE', '600'))

# Global flag for manual refresh
refresh_requested = threading.Event()

# Boot timestamp
boot_timestamp = datetime.now()

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================
def validate_configuration():
    """Validate critical environment variables on startup."""
    errors = []
    warnings = []

    # Critical configuration
    if not API_KEY:
        errors.append("API_KEY is required for bus/train APIs")
    if not BUS_STOP_CODE_A:
        errors.append("BUS_STOP_CODE_A is required")
    if not BUS_API_URL or BUS_API_URL == 'Not Found - bus API url':
        errors.append("API_BUS_URL is not configured")
    if not TRAIN_API_URL or TRAIN_API_URL == 'Not Found - train API url':
        errors.append("API_TRAIN_URL is not configured")
    if not API_BUS_STOP_INFO_URL:
        warnings.append("API_BUS_STOP_INFO_URL not set - using default")

    # ... rest of validation

    # Journey time configuration
    if SHOW_JOURNEY_TIME:
        if not JOURNEY_DESTINATION:
            warnings.append("SHOW_JOURNEY_TIME enabled but JOURNEY_DESTINATION not set")
        if not BUS_SERVICES_TO_TRACK:
            warnings.append("SHOW_JOURNEY_TIME enabled but BUS_SERVICES_TO_TRACK not set")
        if ROUTING_API_PROVIDER == 'google' and not GOOGLE_MAPS_API_KEY:
            errors.append("Google Maps selected but GOOGLE_MAPS_API_KEY not set")

    # Optional but recommended
    if not HOME_ASSISTANT_API_URL:
        warnings.append("HOME_ASSISTANT_API_URL not set - weather disabled")
    if not HOME_ASSISTANT_TOKEN:
        warnings.append("HOME_ASSISTANT_TOKEN not set - weather disabled")
    if MQTT_ENABLED and not MQTT_BROKER:
        warnings.append("MQTT enabled but MQTT_BROKER not set")
    if not HOME_ASSISTANT_DASHBOARD_URL:
        warnings.append("HOME_ASSISTANT_DASHBOARD_URL not set - ha_screen disabled")
    if not os.path.exists(SCHEDULE_CONFIG_PATH):
        warnings.append(
            f"schedule_config.json not found at {SCHEDULE_CONFIG_PATH} - "
            f"falling back to a schedule derived from WAKE_HOUR/SLEEP_HOUR"
        )
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN:
        warnings.append(
            "HOME_ASSISTANT_API_URL/HOME_ASSISTANT_TOKEN not set - "
            "day-type resolution will always fall back to DAY_TYPE_FALLBACK"
        )

    # Log results
    if errors:
        logging.error("=" * 50)
        logging.error("CONFIGURATION ERRORS FOUND:")
        for error in errors:
            logging.error(f"  ✗ {error}")
        logging.error("=" * 50)
        return False

    if warnings:
        logging.warning("Configuration warnings:")
        for warning in warnings:
            logging.warning(f"  ⚠ {warning}")

    logging.info("✓ Configuration validated successfully")
    return True
