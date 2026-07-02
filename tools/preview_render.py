#!/usr/bin/env python3
"""Render the real display draw functions to a PNG, without any e-ink
hardware or waveshare/pigpio dependency.

app/render/*.py and app/config.py have no hardware imports — only
app/main.py (and the waveshare driver) do — so the actual drawing code
can run anywhere with Pillow + python-dotenv installed (both already in
requirements.txt). This script exercises that code path directly against
a fake DisplayManager, then composites the resulting black/red image
buffers into a single viewable PNG (black -> black, red -> red pixels),
so layout/rendering changes can be visually checked without a Pi.

Usage:
    python3 tools/preview_render.py [--screen combined|debug|daytime|sleep|boot]
                                     [--disruption] [--no-weather]
                                     [--no-journey] [--manual-refresh]
                                     [--out PATH]

Requires: pip install Pillow python-dotenv (see requirements.txt).
Does NOT preview ha_screen — that screen fetches a live HA dashboard
screenshot over the network, which isn't something to fake locally.
sleep_screen (the true overnight screen) IS previewable — it's purely
local PIL drawing, no network fetch.
--screen boot uses fixed fake connectivity results (reusing --no-weather/
--no-journey to simulate failed checks) so it never touches the network
either.
"""
import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, 'app')
sys.path.insert(0, APP_DIR)

from PIL import Image, ImageDraw  # noqa: E402


class FakeDisplayManager:
    """Same interface as render.common.DisplayManager's clear_images()/
    display(), but keeps the buffers in memory instead of touching
    hardware."""
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.black_image = Image.new('1', (width, height), 255)
        self.red_image = Image.new('1', (width, height), 255)

    def clear_images(self):
        self.black_image.paste(255, (0, 0, self.width, self.height))
        self.red_image.paste(255, (0, 0, self.width, self.height))
        return ImageDraw.Draw(self.black_image), ImageDraw.Draw(self.red_image)

    def display(self):
        pass  # no-op: nothing to push to hardware


class FakeMQTTClient:
    """Just enough of MQTTClient's interface for display_combined_view()'s
    mqtt_connected icon to be previewable."""
    def __init__(self, connected):
        self.connected = connected


def build_scenario(args):
    """Fake bus/train/weather/journey data shaped like the real fetchers'
    return values (see app/fetchers.py)."""
    bus_info = [
        ('12', [3, 15, 28], ['SEA']),
        ('45', [7, 22], ['SDA']),
        ('858', [0, 18, 35], ['LSD']),
    ]

    if args.disruption:
        train_info = {
            'disruptions': [{
                'Line': 'North-South Line',
                'Direction': 'Towards Jurong East',
                'Stations': ['Orchard', 'Somerset', 'Dhoby Ghaut'],
            }],
            'content': 'Free bridging buses available at affected stations.',
        }
    else:
        train_info = "No Disruptions Today!"

    weather_info = None if args.no_weather else {
        'temperature': 29,
        'condition': 'partlycloudy',
        'humidity': 68,
        'aqi': 57,
        'aqi_label': 'AQI',
        'aqi_category': 'Moderate',
    }

    journey_times = {}
    if not args.no_journey:
        journey_times = {
            '12': {'total_time': 22, 'arrival_time': (datetime.now()).strftime('%H:%M')},
        }

    return bus_info, train_info, weather_info, journey_times


def render_combined(args):
    from render.common import DisplayManager, get_font  # noqa: F401 (import path sanity check)
    from render import common as rc
    from render.bus_train import display_combined_view

    mgr = FakeDisplayManager(rc.SCREEN_WIDTH, rc.SCREEN_HEIGHT)
    font = rc.get_font(32)
    bus_info, train_info, weather_info, journey_times = build_scenario(args)
    mqtt_client = FakeMQTTClient(connected=True)

    display_combined_view(
        mgr, font, bus_info, train_info, weather_info,
        journey_times=journey_times, manual_refresh=args.manual_refresh,
        mqtt_client=mqtt_client,
    )
    return mgr


def render_debug(args):
    from render import common as rc
    from render.debug_screen import display_debug_screen

    mgr = FakeDisplayManager(rc.SCREEN_WIDTH, rc.SCREEN_HEIGHT)
    # display_debug_screen() ends with time.sleep(5) to hold the screen on
    # real hardware — patch it out so the preview returns immediately.
    import time
    real_sleep = time.sleep
    time.sleep = lambda *_a, **_k: None
    try:
        display_debug_screen(mgr, datetime.now().strftime("%H:%M on %d %b %Y"))
    finally:
        time.sleep = real_sleep
    return mgr


def render_daytime(args):
    from render import common as rc
    from render.daytime_screen import display_daytime_screen, build_daytime_model

    mgr = FakeDisplayManager(rc.SCREEN_WIDTH, rc.SCREEN_HEIGHT)
    # Fixed timestamp: 11:45 exercises the longest word-clock string family
    # ("Quarter to twelve"); weather honors --no-weather via build_scenario.
    _, _, weather_info, _ = build_scenario(args)
    model = build_daytime_model(datetime(2026, 7, 2, 11, 45), weather_info)
    display_daytime_screen(mgr, model)
    return mgr


def render_sleep(args):
    from render import common as rc
    from render.sleep_screen import display_sleep_screen

    mgr = FakeDisplayManager(rc.SCREEN_WIDTH, rc.SCREEN_HEIGHT)
    display_sleep_screen(mgr, next_wake_time="06:30")
    return mgr


def render_boot(args):
    from render import common as rc
    from render.boot_screen import display_boot_checklist

    mgr = FakeDisplayManager(rc.SCREEN_WIDTH, rc.SCREEN_HEIGHT)
    # Fixed fake results — boot_screen's checks hit real sockets/HTTP, which
    # this hardware-free preview must never touch. Reuses --no-weather/
    # --no-journey as a cheap way to simulate a failed check without adding
    # new CLI flags just for this.
    fake_results = [
        ("Network", True),
        ("Internet", True),
        ("LTA API", not args.no_journey),
        ("Home Assistant", not args.no_weather),
    ]
    display_boot_checklist(mgr, datetime.now().strftime("%H:%M on %d %b %Y"), check_results=fake_results)
    return mgr


def composite_preview(mgr):
    """Merge the black/red 1-bit buffers into one viewable RGB image."""
    preview = Image.new('RGB', (mgr.width, mgr.height), 'white')
    black_px = mgr.black_image.load()
    red_px = mgr.red_image.load()
    out_px = preview.load()
    for y in range(mgr.height):
        for x in range(mgr.width):
            if black_px[x, y] == 0:
                out_px[x, y] = (0, 0, 0)
            elif red_px[x, y] == 0:
                out_px[x, y] = (200, 30, 30)
    return preview


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--screen', choices=['combined', 'debug', 'daytime', 'sleep', 'boot'], default='combined',
                         help='Which screen to render (default: combined)')
    parser.add_argument('--disruption', action='store_true', help='Simulate a train disruption instead of "all clear"')
    parser.add_argument('--no-weather', action='store_true', help='Simulate weather being unavailable')
    parser.add_argument('--no-journey', action='store_true', help='Omit journey-time data')
    parser.add_argument('--manual-refresh', action='store_true', help='Simulate a manual (MQTT-triggered) refresh')
    parser.add_argument('--out', default=os.path.join(REPO_ROOT, 'tools', 'preview_output.png'),
                         help='Output PNG path (default: tools/preview_output.png, gitignored)')
    args = parser.parse_args()

    dispatch = {
        'combined': render_combined,
        'debug': render_debug,
        'daytime': render_daytime,
        'sleep': render_sleep,
        'boot': render_boot,
    }
    mgr = dispatch[args.screen](args)

    preview = composite_preview(mgr)
    preview.save(args.out)
    print(f"Saved {args.out} ({mgr.width}x{mgr.height})")


if __name__ == '__main__':
    main()
