"""Outside the wake window: fetches a rendered Home Assistant dashboard
screenshot and pushes it straight to the black buffer (no draw calls). Kept
under this name for Phase 1 — the "daytime vs. true sleep" screen split is a
Phase 2 concept change, deliberately not made here.
"""
import io
import logging

import requests
from PIL import Image

from config import (
    SLEEP_SCREEN_DASHBOARD, SLEEP_SCREEN_EINK_MODE, SLEEP_SCREEN_ZOOM,
    SLEEP_SCREEN_WAIT, SLEEP_SCREEN_THEME,
)
from fetchers import http_session


def display_sleep_screen(display_mgr, image_url):
    """Fetch and display the sleep screen from Home Assistant."""
    url_param = (f"{SLEEP_SCREEN_DASHBOARD}/0?viewport="
                f"{display_mgr.epd.width}x{display_mgr.epd.height}"
                f"&eink={SLEEP_SCREEN_EINK_MODE}"
                f"&zoom={SLEEP_SCREEN_ZOOM}"
                f"&wait={SLEEP_SCREEN_WAIT}"
                f"&theme={SLEEP_SCREEN_THEME}")

    full_url = image_url + url_param
    logging.info(f"Fetching sleep screen from: {full_url}")

    try:
        response = http_session.get(full_url, timeout=50)
        response.raise_for_status()

        image = Image.open(io.BytesIO(response.content))
        bw_image = image.convert('L')
        red_image = Image.new('1', (display_mgr.epd.width, display_mgr.epd.height), 255)

        logging.info("Displaying sleep screen...")
        display_mgr.epd.display(display_mgr.epd.getbuffer(bw_image),
                               display_mgr.epd.getbuffer(red_image))
        return True

    except requests.RequestException as e:
        logging.error(f"Failed to fetch sleep screen: {e}")
        return False
