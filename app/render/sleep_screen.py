"""sleep_screen: the true overnight screen — minimal, locally-PIL-drawn (no
network fetch, no Puppeteer). Shown during its own schedule window (default
~21:00-06:00), and has the highest precedence of the four screens ("ultimate
override" — always wins regardless of day-type or the other three screens'
windows). While active, main.py skips fetch_data_parallel() entirely, same
as ha_screen.
"""
import logging

from config import SCREEN_WIDTH, SCREEN_HEIGHT, FONT_SECTION
from render.common import get_font, draw_mdi_icon, MDI


def display_sleep_screen(display_mgr, next_wake_time=None):
    """Draw the minimal overnight sleep screen: MDI.WEATHER_NIGHT icon and
    (if provided) the next scheduled wake time. `next_wake_time` is a
    pre-formatted 'HH:MM' string — callers compute it from the schedule
    (scheduler.get_next_wake_time()) so this function stays a pure drawing
    function with no scheduler import.
    """
    draw, draw_r = display_mgr.clear_images()

    draw_mdi_icon(
        draw, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40,
        MDI.WEATHER_NIGHT, size=80, color=0, anchor="mm",
    )

    if next_wake_time:
        draw_r.text(
            (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 60),
            f"Next wake: {next_wake_time}",
            font=get_font(FONT_SECTION),
            fill=0,
            anchor="mm",
        )

    display_mgr.display()
    logging.info(f"sleep_screen displayed (next wake: {next_wake_time})")
