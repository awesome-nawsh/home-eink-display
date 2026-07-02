"""Dev-only diagnostic screen: dumps resolved config values in two columns.
Shown once at boot when DEBUG_SKIP_TIME_CHECK=true."""
import logging
import time

from config import *
from scheduler import load_schedule_config, SCREEN_NAMES
from render.common import get_font, get_font_bold, draw_mdi_icon, MDI


def display_debug_screen(display_mgr, boot_time):
    """Display debug information: resolved config, the real schedule windows
    (from schedule_config.json — not the legacy WAKE_HOUR/SLEEP_HOUR, which
    are only the fallback inputs), and today's resolved day-type."""
    draw, draw_r = display_mgr.clear_images()

    schedule = load_schedule_config(SCHEDULE_CONFIG_PATH, WAKE_HOUR, SLEEP_HOUR)
    screens = schedule['screens']

    try:
        # Lazy import: pulls in fetchers/day_type (and one quick HA call)
        # only for this dev-only screen, never at module import time.
        from fetchers import get_day_type_sensors
        from day_type import day_type_cache, resolve_todays_day_type
        day_type = resolve_todays_day_type(day_type_cache, get_day_type_sensors, DAY_TYPE_FALLBACK)
    except Exception as e:
        day_type = f"error ({e})"

    draw_mdi_icon(draw, HEADER_ICON_X, HEADER_ICON_Y, MDI.BUS_MARKER, size=40, color=0)
    draw_r.text((70, 15), "DEBUG MODE", font=get_font_bold(FONT_HEADER), fill=0)
    draw_r.line((SCREEN_MARGIN, 50, SCREEN_WIDTH - SCREEN_MARGIN, 50), fill=0, width=DIVIDER_WIDTH)

    debug_font = get_font(11)
    y_pos = 60
    line_spacing = 17
    column_split = COLUMN_OFFSET

    left_vars = [
        f"Boot: {boot_time}",
        f"Log: {LOG_LEVEL}",
        "",
        f"Origin: {BUS_STOP_CODE_A}",
        f"Name: {HEADER_A[:25]}",
        "",
        f"Journey: {'On' if SHOW_JOURNEY_TIME else 'Off'}",
        f"Dest: {JOURNEY_DESTINATION[:22]}" if JOURNEY_DESTINATION else "Dest: Not Set",
        f"API: {ROUTING_API_PROVIDER.upper()}",
        f"Track: {','.join(BUS_SERVICES_TO_TRACK[:3])}" if BUS_SERVICES_TO_TRACK else "Track: None",
        "",
        f"Day type: {day_type}",
    ]

    right_vars = [
        f"Wake Int: {WAKE_INTERVAL}s",
        f"Sleep Int: {SLEEP_INTERVAL}s",
        "",
        f"MQTT: {'On' if MQTT_ENABLED else 'Off'}",
        f"Broker: {MQTT_BROKER}" if MQTT_ENABLED else "",
        "",
        f"Cache: {CACHE_DURATION}s",
        f"Weather: {WEATHER_CACHE_DURATION}s",
        f"Journey: {JOURNEY_TIME_CACHE_DURATION}s",
        "",
        "Schedule:",
    ] + [
        f"{name}: {screens[name]['start']}-{screens[name]['end']}"
        for name in SCREEN_NAMES
    ]

    y = y_pos
    for var in left_vars:
        if var:
            draw.text((15, y), var, font=debug_font, fill=0)
        y += line_spacing

    y = y_pos
    for var in right_vars:
        if var:
            draw.text((column_split + 10, y), var, font=debug_font, fill=0)
        y += line_spacing

    draw_r.text((15, SCREEN_HEIGHT - 25),
               "Displaying for 5 seconds...",
               font=get_font(BOTTOM_FONT_SIZE), fill=0)

    display_mgr.display()
    logging.info("DEBUG MODE: Displaying environment variables for 5 seconds")
    time.sleep(5)
