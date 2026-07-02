"""daytime_screen: a word clock ("Quarter past two"), the date, and current
weather. Third of the four screens in precedence (above only ha_screen; it's
also the fallback when no screen's window covers the current time).

The clock is deliberately quarter-hour-granular: e-ink full refreshes are
slow and flash the whole panel, so the screen redraws only when the
quarter-hour bucket (or the weather) changes — 4 refreshes/hour, aligned to
:00/:15/:30/:45. build_daytime_model() is the pure half: main.py compares
its 'bucket' between ticks to decide when a redraw is due.
"""
import logging

from config import SCREEN_WIDTH, FONT_CLOCK, FONT_HEADER, FONT_SECTION
from render.common import get_font, get_font_bold, get_weather_icon, draw_mdi_icon

_HOUR_WORDS = ['twelve', 'one', 'two', 'three', 'four', 'five', 'six',
               'seven', 'eight', 'nine', 'ten', 'eleven']


def time_in_words(hour, quarter):
    """The quarter-hour in words: (14, 1) -> "Quarter past two". `quarter`
    is minutes // 15; "quarter to" phrasings name the NEXT hour. Pure."""
    this_hour = _HOUR_WORDS[hour % 12]
    next_hour = _HOUR_WORDS[(hour + 1) % 12]
    phrase = {
        0: f"{this_hour} o'clock",
        1: f"quarter past {this_hour}",
        2: f"half past {this_hour}",
        3: f"quarter to {next_hour}",
    }[quarter]
    return phrase[0].upper() + phrase[1:]


def build_daytime_model(now, weather_info):
    """Pure: everything display_daytime_screen() draws, plus the 'bucket'
    tuple main.py compares between ticks — a redraw is due exactly when the
    bucket changes (new quarter-hour, new day, or the weather content
    changed)."""
    quarter = now.minute // 15
    weather_summary = None
    if weather_info:
        weather_summary = (weather_info.get('temperature'),
                           weather_info.get('condition'),
                           weather_info.get('humidity'),
                           weather_info.get('aqi'),
                           weather_info.get('aqi_category'))
    return {
        'bucket': (now.date().isoformat(), now.hour, quarter, weather_summary),
        'time_words': time_in_words(now.hour, quarter),
        'date': f"{now:%A} {now.day} {now:%B}",
        'weather': weather_info,
    }


def display_daytime_screen(display_mgr, model):
    """Draw the word clock / date / weather view from a build_daytime_model()
    dict and push it to the panel."""
    draw, draw_r = display_mgr.clear_images()
    center_x = SCREEN_WIDTH // 2

    draw.text((center_x, 150), model['time_words'],
              font=get_font_bold(FONT_CLOCK), fill=0, anchor="mm")
    draw.text((center_x, 245), model['date'],
              font=get_font(FONT_HEADER), fill=0, anchor="mm")

    weather = model['weather']
    if weather:
        icon_size = 48
        gap = 16
        row_y = 360
        temp = weather.get('temperature')
        temp_text = f"{temp}°C" if temp is not None else ""
        temp_font = get_font_bold(FONT_CLOCK // 2)

        # Center the icon + temperature as one group: measure the text, then
        # lay both out side by side around the midline.
        temp_width = draw.textlength(temp_text, font=temp_font) if temp_text else 0
        group_width = icon_size + (gap + temp_width if temp_text else 0)
        icon_x = center_x - group_width / 2 + icon_size / 2

        draw_mdi_icon(draw, icon_x, row_y, get_weather_icon(weather.get('condition')),
                      size=icon_size, color=0, anchor="mm")
        if temp_text:
            draw_r.text((icon_x + icon_size / 2 + gap, row_y), temp_text,
                        font=temp_font, fill=0, anchor="lm")

        # HA condition strings are squashed lowercase ('partlycloudy'); give
        # the known multi-word ones a readable form before title-casing.
        raw = weather.get('condition') or ''
        condition = {'partlycloudy': 'partly cloudy',
                     'lightning-rainy': 'thundery'}.get(raw, raw).replace('-', ' ').title()
        parts = [condition]
        if weather.get('humidity') is not None:
            parts.append(f"{weather['humidity']}%")
        if weather.get('aqi') is not None:
            reading = f"{weather.get('aqi_label', 'AQI')} {weather['aqi']}"
            if weather.get('aqi_category'):
                reading += f" ({weather['aqi_category']})"
            parts.append(reading)
        draw.text((center_x, row_y + 55), "  ·  ".join(parts),
                  font=get_font(FONT_SECTION), fill=0, anchor="mm")

    display_mgr.display()
    logging.info(f"daytime_screen displayed ({model['time_words']}, "
                 f"weather={'yes' if weather else 'no'})")
