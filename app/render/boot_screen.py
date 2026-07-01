"""Boot-time connectivity checklist, replacing the old static
"System Starting..." text. All checks run first (boot_checks.run_all_checks()),
then a single draw + display() call — e-ink full refresh is slow, so this
must never do one physical refresh per check.
"""
import logging

from config import (
    SCREEN_MARGIN, SCREEN_WIDTH, SCREEN_HEIGHT, DIVIDER_WIDTH,
    HEADER_ICON_X, HEADER_ICON_Y, HEADER_TEXT_Y, FONT_HEADER, FONT_TIMESTAMP,
)
from render.common import get_font, get_font_bold, draw_mdi_icon, MDI
from boot_checks import run_all_checks


def display_boot_checklist(display_mgr, boot_time, check_results=None):
    """check_results: optional pre-computed [(label, bool), ...] — lets
    tests/preview inject fixed results instead of hitting the network.
    Defaults to boot_checks.run_all_checks() when None."""
    if check_results is None:
        check_results = run_all_checks()

    draw, draw_r = display_mgr.clear_images()

    draw_mdi_icon(draw, HEADER_ICON_X, HEADER_ICON_Y, MDI.BUS_MARKER, size=50, color=0)
    draw.text((85, HEADER_TEXT_Y), "System Starting...", font=get_font_bold(FONT_HEADER), fill=0)
    draw.line((SCREEN_MARGIN, 55, SCREEN_WIDTH - SCREEN_MARGIN, 55), fill=0, width=DIVIDER_WIDTH)

    y = 80
    for label, ok in check_results:
        icon = MDI.CHECK_CIRCLE if ok else MDI.ALERT_CIRCLE
        draw_mdi_icon(draw, 30, y, icon, size=24, color=0)
        draw.text((65, y + 2), label, font=get_font(20), fill=0)
        y += 34

    draw_r.text(
        (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 25),
        f"Booted: {boot_time}",
        font=get_font(FONT_TIMESTAMP),
        fill=0,
        anchor="mm",
    )

    display_mgr.display()
    logging.info(f"Boot checklist displayed: {check_results}")
