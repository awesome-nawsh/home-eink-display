"""ha_screen: fetches a rendered Home Assistant dashboard screenshot and
pushes it straight to the black buffer (no draw calls). Shown per its own
schedule entry in schedule_config.json (see scheduler.py) — highest
precedence of the three screens, regardless of day-type. Renamed from
"sleep screen" in Phase 2, now that "sleep" is a schedule window this screen
is driven by rather than something baked into its identity.
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


def display_ha_screen(display_mgr, image_url):
    """Fetch and display the ha_screen dashboard image from Home Assistant."""
    url_param = (f"{SLEEP_SCREEN_DASHBOARD}/0?viewport="
                f"{display_mgr.epd.width}x{display_mgr.epd.height}"
                f"&eink={SLEEP_SCREEN_EINK_MODE}"
                f"&zoom={SLEEP_SCREEN_ZOOM}"
                f"&wait={SLEEP_SCREEN_WAIT}"
                f"&theme={SLEEP_SCREEN_THEME}")

    full_url = image_url + url_param
    logging.info(f"Fetching ha_screen dashboard from: {full_url}")

    try:
        response = http_session.get(full_url, timeout=50)
        response.raise_for_status()

        image = Image.open(io.BytesIO(response.content))
        bw_image = image.convert('L')
        red_image = Image.new('1', (display_mgr.epd.width, display_mgr.epd.height), 255)

        logging.info("Displaying ha_screen...")
        display_mgr.epd.display(display_mgr.epd.getbuffer(bw_image),
                               display_mgr.epd.getbuffer(red_image))
        return True

    except requests.RequestException as e:
        logging.error(f"Failed to fetch ha_screen dashboard: {e}")
        return False
