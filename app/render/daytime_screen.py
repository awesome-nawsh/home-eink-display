"""daytime_screen: placeholder, third of the four screens in precedence
(above only ha_screen; it's also the fallback when no screen's window covers
the current time). Currently just a centered "Day time screen" message —
real content is deferred to a later phase (see todo.md).
"""
import logging

from config import SCREEN_WIDTH, SCREEN_HEIGHT, FONT_HEADER
from render.common import get_font_bold


def display_daytime_screen(display_mgr):
    """Draw the daytime_screen placeholder and push it to the panel."""
    draw, draw_r = display_mgr.clear_images()

    draw.text(
        (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2),
        "Day time screen",
        font=get_font_bold(FONT_HEADER),
        fill=0,
        anchor="mm",
    )

    display_mgr.display()
    logging.info("daytime_screen displayed (placeholder)")
