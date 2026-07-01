"""Entry point / orchestration only.

Config loading, data fetching, and rendering all live in sibling modules
(config, health, fetchers, mqtt_client, render/*) — this file just wires
them together: startup validation, hardware init, the boot sequence, and
the main wake/sleep/fetch/render loop.
"""
import sys
import time
import logging
import traceback
import atexit
import signal
from datetime import datetime

from config import *
from health import watchdog, system_health
from fetchers import cache, fetch_data_parallel, http_session
from mqtt_client import MQTTClient
from render.common import DisplayManager, draw_mdi_icon, get_font, get_font_bold, MDI
from render.bus_train import display_combined_view
from render.debug_screen import display_debug_screen
from render.sleep_screen import display_sleep_screen

from waveshare_epd import epd7in5b_V2
import pigpio  # GPIO backend used transitively by the waveshare driver; imported
                # here (as in the pre-split main.py) so a missing/broken pigpio
                # install fails fast at startup rather than deep inside epd.init().

# ============================================================================
# CLEANUP AND SIGNAL HANDLING
# ============================================================================
def cleanup():
    """Cleanup function to run on exit."""
    try:
        logging.info("Starting cleanup...")

        if 'mqtt_client' in globals() and mqtt_client:
            mqtt_client.disconnect()
            logging.info("MQTT disconnected")

        if http_session:
            http_session.close()
            logging.info("HTTP session closed")

        system_health.log_stats()

        logging.info("Cleanup completed successfully")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

atexit.register(cleanup)

def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============================================================================
# MAIN LOOP
# ============================================================================
def is_in_wake_window(current_hour):
    """Determine if current time is within the wake window."""
    if WAKE_HOUR > SLEEP_HOUR:
        return (current_hour >= WAKE_HOUR) or (current_hour < SLEEP_HOUR)
    else:
        return (current_hour >= WAKE_HOUR) and (current_hour < SLEEP_HOUR)

def main():
    """Main application loop."""
    global mqtt_client
    mqtt_client = None

    try:
        logging.info("=" * 60)
        logging.info("Bus Arrival Display with API-based Journey Times")
        logging.info("=" * 60)

        if not validate_configuration():
            logging.error("Configuration validation failed. Please check your .env file.")
            return 1

        # Log journey configuration
        if SHOW_JOURNEY_TIME:
            logging.info(f"Journey Time Tracking ENABLED")
            logging.info(f"  Routing API: {ROUTING_API_PROVIDER.upper()}")
            logging.info(f"  Origin: Bus stop {BUS_STOP_CODE_A}")
            logging.info(f"  Destination: {JOURNEY_DESTINATION}")
            logging.info(f"  Tracking services: {', '.join(BUS_SERVICES_TO_TRACK)}")
        else:
            logging.info("Journey time tracking DISABLED")

        mqtt_client = MQTTClient()

        epd = epd7in5b_V2.EPD()
        epd.init()
        epd.Clear()

        display_mgr = DisplayManager(epd)

        boot_time = datetime.now().strftime("%H:%M on %d %b %Y")

        if DEBUG_SKIP_TIME_CHECK:
            display_debug_screen(display_mgr, boot_time)
        else:
            draw, draw_r = display_mgr.clear_images()
            boot_font = get_font_bold(FONT_LARGE)

            draw_mdi_icon(draw, HEADER_ICON_X, HEADER_ICON_Y, MDI.BUS_MARKER, size=HEADER_ICON_SIZE, color=0)

            draw.text((85, HEADER_TEXT_Y), "System Starting...", font=boot_font, fill=0)
            draw_r.text((COLUMN_OFFSET - 100, SCREEN_HEIGHT // 2),
                       f"Booted: {boot_time}", font=get_font(FONT_TIMESTAMP), fill=0)

            display_mgr.display()

        default_font = get_font(BUS_NUMBER_FONT_SIZE)
        is_sleeping = False
        stats_counter = 0

        while True:
            watchdog.feed()

            if not watchdog.check():
                logging.critical("Watchdog detected stuck loop - restarting...")
                return 1

            current_hour = datetime.now().hour
            manual_refresh = False

            if refresh_requested.is_set():
                logging.info("Processing manual refresh request")
                manual_refresh = True
                refresh_requested.clear()
                cache.clear()

                if is_sleeping:
                    logging.info("Waking display for manual refresh")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False

            if not DEBUG_SKIP_TIME_CHECK:
                if not is_in_wake_window(current_hour) and not manual_refresh:
                    if not is_sleeping:
                        logging.info(f"Outside wake window. Entering sleep mode until {WAKE_HOUR}:00")

                        if mqtt_client:
                            mqtt_client.publish_status("sleeping")

                        if HOME_ASSISTANT_SLEEP_URL and display_sleep_screen(display_mgr, HOME_ASSISTANT_SLEEP_URL):
                            logging.debug("Sleep screen displayed successfully")
                            epd.sleep()
                            is_sleeping = True
                        else:
                            logging.warning("Could not display sleep screen, will retry")

                    time.sleep(SLEEP_INTERVAL)
                    continue

                if is_sleeping:
                    logging.info(f"Waking up display")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False

                    if mqtt_client:
                        mqtt_client.publish_status("awake")
            else:
                if is_sleeping:
                    logging.info("DEBUG mode: Waking display")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False

            # Fetch all data including API-based journey times
            bus_info, train_info, weather_info, journey_times = fetch_data_parallel(force_refresh=manual_refresh)

            display_combined_view(display_mgr, default_font, bus_info, train_info, weather_info,
                                journey_times=journey_times, manual_refresh=manual_refresh, mqtt_client=mqtt_client)

            if mqtt_client:
                mqtt_client.publish_status("idle")

            stats_counter += 1
            if stats_counter >= 10:
                system_health.log_stats()
                stats_counter = 0

            time.sleep(WAKE_INTERVAL)

    except IOError as e:
        logging.error(f"IO Error: {e}")
        logging.debug(traceback.format_exc())
        return 1

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
        return 0

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        logging.debug(traceback.format_exc())
        return 1

    finally:
        if mqtt_client:
            mqtt_client.disconnect()
        epd7in5b_V2.epdconfig.module_exit(cleanup=True)
        logging.info("Application terminated")

if __name__ == "__main__":
    sys.exit(main())
