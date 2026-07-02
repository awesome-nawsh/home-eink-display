"""Entry point / orchestration only.

Config loading, data fetching, and rendering all live in sibling modules
(config, health, fetchers, mqtt_client, render/*) — this file just wires
them together: startup validation, hardware init, the boot sequence, and
the main scheduler/fetch/render loop.
"""
import sys
import time
import logging
import traceback
import atexit
import signal
from datetime import datetime

import config
from config import *
from health import system_health, sd_notify
from fetchers import cache, fetch_data_parallel, http_session, get_day_type_sensors, get_weather
from mqtt_client import MQTTClient
from render.common import DisplayManager, get_font
from render.bus_train import display_combined_view
from render.debug_screen import display_debug_screen
from render.ha_screen import display_ha_screen
from render.sleep_screen import display_sleep_screen
from render.daytime_screen import display_daytime_screen, build_daytime_model
from render.boot_screen import display_boot_checklist
from scheduler import load_schedule_config, resolve_active_screen, get_next_wake_time, detect_overlaps
from day_type import day_type_cache, resolve_todays_day_type
from reload_watch import get_mtime, has_changed

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
def load_schedule_and_log_overlaps(path):
    """Load the schedule and log its overlap warnings once. Warnings only
    change when the schedule file changes, so they're computed here (at
    startup and on each dynamic reload) rather than every loop tick."""
    schedule = load_schedule_config(path, WAKE_HOUR, SLEEP_HOUR)
    for warning in detect_overlaps(schedule):
        logging.warning(f"Schedule conflict: {warning}")
    return schedule


def run_bus_train_tick(display_mgr, default_font, mqtt_client, manual_refresh, stats_counter):
    """One fetch+render+publish cycle for the bus/train view — shared by the
    normal bus_train_screen branch and DEBUG_SKIP_TIME_CHECK mode so the two
    can't drift. Returns the updated stats_counter."""
    bus_info, train_info, weather_info, journey_times = fetch_data_parallel(force_refresh=manual_refresh)
    display_combined_view(display_mgr, default_font, bus_info, train_info, weather_info,
                          journey_times=journey_times, manual_refresh=manual_refresh, mqtt_client=mqtt_client)

    if mqtt_client:
        mqtt_client.publish_status("idle")

    stats_counter += 1
    if stats_counter >= 10:
        system_health.log_stats()
        stats_counter = 0
    return stats_counter



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

        schedule = load_schedule_and_log_overlaps(SCHEDULE_CONFIG_PATH)
        logging.info(f"Schedule loaded: {schedule['screens']}")
        schedule_mtime = get_mtime(SCHEDULE_CONFIG_PATH)
        env_mtime = get_mtime(config.ENV_FILE_PATH)

        if FORCE_SCREEN:
            logging.warning(f"FORCE_SCREEN={FORCE_SCREEN} active - schedule/day-type resolution bypassed for testing")

        mqtt_client = MQTTClient()

        epd = epd7in5b_V2.EPD()
        epd.init()
        epd.Clear()

        display_mgr = DisplayManager(epd)

        boot_time = datetime.now().strftime("%H:%M on %d %b %Y")

        if DEBUG_SKIP_TIME_CHECK:
            display_debug_screen(display_mgr, boot_time)
        else:
            display_boot_checklist(display_mgr, boot_time)

        default_font = get_font(BUS_NUMBER_FONT_SIZE)
        is_epd_asleep = False
        active_screen = None
        stats_counter = 0
        day_type = None  # stays None under FORCE_SCREEN/debug; set by normal resolution
        last_daytime_bucket = None  # daytime_screen's quarter-hour redraw tracker

        # Tell systemd startup succeeded (Type=notify) — a no-op outside systemd.
        sd_notify('READY=1')

        while True:
            # Watchdog ping: if these stop for WatchdogSec (bus_display.service),
            # systemd kills and restarts the process. This replaces the old
            # in-process Watchdog, which fed and checked itself from this same
            # thread and so could never actually detect a hang.
            sd_notify('WATCHDOG=1')

            manual_refresh = False

            if refresh_requested.is_set():
                logging.info("Processing manual refresh request")
                manual_refresh = True
                refresh_requested.clear()
                cache.clear()

                if is_epd_asleep:
                    logging.info("Waking display for manual refresh")
                    epd.init()
                    epd.Clear()
                    is_epd_asleep = False

            # Dynamic (no-restart) config reload — deliberately scoped to just
            # the schedule and FORCE_SCREEN (config.DYNAMIC_CONFIG_VARS).
            # Everything else still needs a real restart (Phase 3's
            # /api/restart). The MQTT config_reload topic is the fast path;
            # the mtime checks are the backstop for edits made directly on
            # disk (e.g. over SSH) without going through the web UI.
            schedule_changed, schedule_mtime = has_changed(SCHEDULE_CONFIG_PATH, schedule_mtime)
            env_changed, env_mtime = has_changed(config.ENV_FILE_PATH, env_mtime)

            if config_reload_requested.is_set() or env_changed:
                config.reload_dynamic_vars()

            if config_reload_requested.is_set() or schedule_changed:
                schedule = load_schedule_and_log_overlaps(SCHEDULE_CONFIG_PATH)
                logging.info(f"Schedule reloaded: {schedule['screens']}")

            config_reload_requested.clear()

            if DEBUG_SKIP_TIME_CHECK:
                if is_epd_asleep:
                    logging.info("DEBUG mode: Waking display")
                    epd.init()
                    epd.Clear()
                    is_epd_asleep = False

                stats_counter = run_bus_train_tick(display_mgr, default_font, mqtt_client,
                                                   manual_refresh, stats_counter)
                time.sleep(WAKE_INTERVAL)
                continue

            if config.FORCE_SCREEN:  # dotted access — sees live updates from reload_dynamic_vars()
                screen_name = config.FORCE_SCREEN
            else:
                day_type = resolve_todays_day_type(day_type_cache, get_day_type_sensors, DAY_TYPE_FALLBACK)
                screen_name = resolve_active_screen(schedule, day_type, datetime.now())

            # Health/status snapshot for the web panel's status bar
            system_health.write_status_file(
                STATUS_FILE_PATH,
                mqtt_connected=mqtt_client.connected if mqtt_client else False,
                cache_size=len(cache.cache),
                active_screen=screen_name,
                day_type=day_type,
            )

            screen_changed = screen_name != active_screen

            if screen_name == "sleep_screen":
                if screen_changed or manual_refresh:
                    if screen_changed and mqtt_client:
                        mqtt_client.publish_status("sleeping")

                    display_sleep_screen(display_mgr, next_wake_time=get_next_wake_time(schedule))
                    epd.sleep()
                    is_epd_asleep = True

                active_screen = "sleep_screen"
                # sleep_screen is the ultimate override — like ha_screen, it
                # skips fetch_data_parallel() entirely while active (no
                # LTA/weather polling).
                time.sleep(SLEEP_INTERVAL)
                continue

            if screen_name == "ha_screen":
                if screen_changed or manual_refresh:
                    if screen_changed and mqtt_client:
                        mqtt_client.publish_status("sleeping")

                    if HOME_ASSISTANT_DASHBOARD_URL and display_ha_screen(display_mgr, HOME_ASSISTANT_DASHBOARD_URL):
                        logging.debug("ha_screen displayed successfully")
                        epd.sleep()
                        is_epd_asleep = True
                        active_screen = "ha_screen"
                    else:
                        # Leave active_screen unset so screen_changed stays
                        # True next tick and the fetch genuinely retries —
                        # setting it here would suppress the redraw path and
                        # make this log message a lie.
                        logging.warning("Could not display ha_screen, will retry")
                        active_screen = None
                # ha_screen deliberately skips fetch_data_parallel() entirely
                # while active — no LTA/weather polling until the schedule
                # exits this window or a manual refresh forces a redraw.
                time.sleep(SLEEP_INTERVAL)
                continue

            if is_epd_asleep:
                logging.info("Waking up display")
                epd.init()
                epd.Clear()
                is_epd_asleep = False

                if mqtt_client:
                    mqtt_client.publish_status("awake")

            if screen_name == "bus_train_screen":
                stats_counter = run_bus_train_tick(display_mgr, default_font, mqtt_client,
                                                   manual_refresh, stats_counter)
                active_screen = "bus_train_screen"

            else:  # daytime_screen — word clock; redraw only when the quarter-hour
                   # bucket (or the weather shown) changes: 4 flashes/hour, not 120.
                weather_info = get_weather(manual_refresh)  # cache-served most ticks
                model = build_daytime_model(datetime.now(), weather_info)

                if screen_changed or manual_refresh or model['bucket'] != last_daytime_bucket:
                    display_daytime_screen(display_mgr, model)
                    last_daytime_bucket = model['bucket']
                    if mqtt_client:
                        mqtt_client.publish_status("idle")

                active_screen = "daytime_screen"

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
