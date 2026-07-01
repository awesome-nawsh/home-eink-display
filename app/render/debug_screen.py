"""Dev-only diagnostic screen: dumps resolved config values in two columns.
Shown once at boot when DEBUG_SKIP_TIME_CHECK=true."""
import logging
import time

from config import *
from render.common import get_font, get_font_bold, draw_mdi_icon, MDI


def display_debug_screen(display_mgr, boot_time):
    """Display debug information with all environment variables."""
    draw, draw_r = display_mgr.clear_images()

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
        f"Wake: {WAKE_HOUR}:00",
        f"Sleep: {SLEEP_HOUR}:00",
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
        f"APIs configured",
        f"Routing ready",
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
