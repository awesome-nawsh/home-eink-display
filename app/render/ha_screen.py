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
    HA_SCREEN_DASHBOARD, HA_SCREEN_EINK_MODE, HA_SCREEN_ZOOM,
    HA_SCREEN_FORMAT, HA_SCREEN_WAIT, HA_SCREEN_THEME,
)
from fetchers import http_session


def display_ha_screen(display_mgr, image_url):
    """Fetch and display the ha_screen dashboard image from Home Assistant."""
    url_param = (f"{HA_SCREEN_DASHBOARD}/0?viewport="
                f"{display_mgr.epd.width}x{display_mgr.epd.height}"
                f"&eink={HA_SCREEN_EINK_MODE}"
                f"&zoom={HA_SCREEN_ZOOM}"
                f"&wait={HA_SCREEN_WAIT}"
                f"&theme={HA_SCREEN_THEME}")
    if HA_SCREEN_FORMAT:
        url_param += f"&format={HA_SCREEN_FORMAT}"

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
