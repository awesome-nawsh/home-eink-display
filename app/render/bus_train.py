"""The "awake" screen: bus arrivals (left column) plus train disruptions and
weather (right column) — display_combined_view() and its section drawers.
"""
import logging
import textwrap
from datetime import datetime

from config import *
from health import system_health
from render.common import (
    get_font, get_font_bold, draw_mdi_icon, get_weather_icon,
    MDI, BUS_LOAD_MAP_ICON,
)


def draw_timestamp(draw_r, x=None, y=10, manual=False):
    """Draw the last updated timestamp at the top right of the screen."""
    now = datetime.now()
    formatted_time = now.strftime("%H:%M")
    formatted_date = now.strftime("%d %b %Y")

    timestamp_font = get_font(FONT_TIMESTAMP)
    small_font = get_font(FONT_SMALL)

    time_text = f"Updated: {formatted_time}"
    if manual:
        time_text += " ★"

    if x is None:
        # anchor="ra" (right, ascender) pins the text's right edge to x and
        # keeps the same top-aligned vertical placement as the default
        # anchor — equivalent to the old manual bbox-width right-align math.
        draw_r.text((SCREEN_WIDTH - TEXT_RIGHT_MARGIN, y), time_text, font=timestamp_font, fill=0, anchor="ra")
    else:
        draw_r.text((x, y), time_text, font=timestamp_font, fill=0)

    draw_r.text((SCREEN_WIDTH - TEXT_RIGHT_MARGIN, y + 22), formatted_date, font=small_font, fill=0, anchor="ra")

def draw_bus_section(draw, draw_r, bus_info, font, y_start, load_font, journey_times=None):
    """Draw the bus arrival section with journey times and destination header.

    bus_info=None means the bus API is failing and nothing recent enough is
    cached (see fetchers._stale_or_unavailable) — rendered as an explicit
    error. An empty list is a genuine "nothing arriving" and renders blank."""
    y = y_start
    bus_number_font = get_font_bold(BUS_NUMBER_FONT_SIZE)
    journey_font = get_font(FONT_TIMESTAMP)
    dest_header_font = get_font(FONT_MEDIUM)

    if bus_info is None:
        error_y = y + BUS_BOX_TOP_GAP
        draw_mdi_icon(draw_r, BUS_SECTION_X, error_y, MDI.ALERT_CIRCLE, size=24, color=0)
        draw_r.text((BUS_SECTION_X + 32, error_y + 2), "Bus data unavailable", font=get_font(FONT_SECTION), fill=0)
        draw.text((BUS_SECTION_X + 32, error_y + 30), "Bus arrival API is not responding", font=get_font(FONT_MEDIUM), fill=0)
        return y + BUS_BOX_Y_SPACING

    # Get display name for destination
    dest_display = JOURNEY_DESTINATION_SHORT if JOURNEY_DESTINATION_SHORT else JOURNEY_DESTINATION
    if len(dest_display) > 25:
        dest_display = dest_display[:22] + "..."

    # Draw destination header at top if journey time is enabled
    if SHOW_JOURNEY_TIME and journey_times and dest_display:
        header_y = y
        draw_mdi_icon(draw_r, JOURNEY_ICON_X, header_y, MDI.MAP_MARKER_DISTANCE, size=20, color=0)
        draw.text((50, header_y + 2), f"Journeys to: {dest_display}", font=dest_header_font, fill=0)
        draw.line((BUS_SECTION_X, header_y + 26, COLUMN_OFFSET, header_y + 26), fill=0, width=1)
        y += JOURNEY_HEADER_GAP

    for service_no, arrival_times, load_rates in bus_info:
        # Draw bus number box
        box_top = y + BUS_BOX_TOP_GAP
        box_height = BUS_BOX_HEIGHT
        box_center_y = box_top + (box_height / 2)

        draw.rectangle((BUS_SECTION_X, box_top, BUS_SECTION_X + BUS_BOX_WIDTH, box_top + box_height), fill=0)

        # Bus number — anchor="lm" (left, middle) vertically centers on
        # box_center_y using the font's ascender/descender metrics rather
        # than this specific string's ink bbox, replacing the old manual
        # getbbox()-height centering. Slightly more consistent than before
        # (no longer shifts a couple px depending on which digits are
        # present), but is a real few-px change from the old bbox-based
        # math — worth a visual check next time the panel is verified.
        draw.text((50, box_center_y - 5), service_no, font=bus_number_font, fill=255, anchor="lm")

        # Arrival times - show "Arr" for 0 minutes
        times_display = []
        for time in arrival_times:
            if time <= 0:
                times_display.append("Arr")
            else:
                times_display.append(str(time))

        times_text = " | ".join(times_display)
        draw.text((BUS_TIMES_X, box_center_y), times_text, font=font, fill=0, anchor="lm")

        # Load indicator with icon - UPDATED
        if load_rates:
            load_code = load_rates[0]
            load_text = BUS_LOAD_MAP_TEXT.get(load_code, '?')
            load_size = BUS_LOAD_MAP_SIZE.get(load_code, 0)
            load_icon = BUS_LOAD_MAP_ICON.get(load_code)

            # Calculate vertical center for load text
            load_bbox = load_font.getbbox(load_text)
            load_text_height = load_bbox[3] - load_bbox[1]
            load_text_y = box_center_y + (box_height / 4) - (load_text_height / 2) + LOAD_TEXT_Y_NUDGE

            # Draw load icon in red (before text)
            if load_icon:
                draw_mdi_icon(draw_r, BUS_LOAD_ICON_X, load_text_y - 2, load_icon, size=LOAD_FONT_SIZE, color=0)
                # Draw load text after icon (adjusted position)
                draw_r.text((BUS_LOAD_TEXT_X, load_text_y), load_text, font=load_font, fill=0)
            else:
                # Fallback if no icon
                draw_r.text((BUS_TIMES_X, load_text_y), load_text, font=load_font, fill=0)

            # Draw load bar
            draw.rectangle((BUS_LOAD_BAR_X1, box_top + 5, BUS_LOAD_BAR_X2, box_top + box_height - 5), fill=255)
            draw_r.rectangle((BUS_LOAD_BAR_X1, box_top + box_height - 5 - load_size // 2,
                            BUS_LOAD_BAR_X2, box_top + box_height - 5), fill=0)

        # Draw journey time if available
        if journey_times and service_no in journey_times:
            details = journey_times[service_no]

            journey_y = box_top + box_height + JOURNEY_Y_GAP

            # Red timer icon
            draw_mdi_icon(draw_r, JOURNEY_ICON_X, journey_y, MDI.TIMER, size=18, color=0)

            # Black journey text
            journey_text = f"{details['total_time']}min (arrive ~{details['arrival_time']})"
            draw.text((48, journey_y + 2), journey_text, font=journey_font, fill=0)

        y += BUS_BOX_Y_SPACING

    return y

def draw_weather_section_right(draw, draw_r, weather_info, x_start):
    """Draw the weather section in right column below train status."""
    if not weather_info:
        return

    # Position weather in right column - fixed position from bottom
    weather_y = SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT

    # Draw separator line
    draw_r.line((x_start, weather_y, SCREEN_WIDTH - SCREEN_MARGIN, weather_y), fill=0, width=1)
    weather_y += WEATHER_POST_DIVIDER_GAP

    # Weather header
    weather_header_font = get_font_bold(FONT_SECTION)
    draw.text((x_start, weather_y), "Weather", font=weather_header_font, fill=0)
    weather_y += WEATHER_HEADER_GAP

    # Draw weather icon
    weather_icon = get_weather_icon(weather_info.get('condition'))
    draw_mdi_icon(draw, x_start, weather_y, weather_icon, size=35, color=0)

    # Draw temperature
    temp = weather_info.get('temperature')
    if temp:
        draw_r.text((x_start + 45, weather_y + 5), f"{temp}°C", font=get_font(FONT_LARGE), fill=0)

    # Draw condition
    condition = weather_info.get('condition', '').title()
    draw.text((x_start, weather_y + 40), condition[:15], font=get_font(FONT_MEDIUM), fill=0)

    # Draw humidity if available
    humidity = weather_info.get('humidity')
    if humidity:
        draw_mdi_icon(draw_r, x_start, weather_y + 65, MDI.WATER_PERCENT, size=18, color=0)
        draw_r.text((x_start + 23, weather_y + 65), f"{humidity}%", font=get_font(BOTTOM_FONT_SIZE), fill=0)

def draw_train_section(draw, draw_r, train_info, train_x):
    """Draw the train disruption section and return final y position."""
    train_font = get_font(FONT_SECTION)
    train_header_font = get_font_bold(FONT_HEADER)

    draw_mdi_icon(draw, train_x - 5, 8, MDI.SUBWAY, size=40, color=0)

    draw_r.text((train_x + 45, HEADER_TEXT_Y), "Train Status", font=train_header_font, fill=0)
    draw_r.line((train_x, HEADER_DIVIDER_Y, SCREEN_WIDTH - SCREEN_MARGIN, HEADER_DIVIDER_Y), fill=0, width=1)

    y_offset = TRAIN_SECTION_Y_OFFSET

    # None means the train API is failing (fetchers._stale_or_unavailable) —
    # distinct from "No Disruptions Today!", which is a real, good answer.
    if train_info is None:
        draw_mdi_icon(draw_r, train_x, y_offset, MDI.ALERT_CIRCLE, size=24, color=0)
        draw_r.text((train_x + 30, y_offset + 2), "Train status", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING
        draw_r.text((train_x + 30, y_offset), "unavailable", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING
        draw.text((train_x + 30, y_offset), "Alerts API is not responding", font=get_font(FONT_MEDIUM), fill=0)
        y_offset += TRAIN_LINE_SPACING
        return y_offset

    if train_info == "No Disruptions Today!":
        draw_mdi_icon(draw_r, train_x, y_offset, MDI.CHECK_CIRCLE, size=24, color=0)

        draw.text((train_x + 30, y_offset + 2), "All trains running", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING
        draw.text((train_x + 30, y_offset), "smoothly today!", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING
        draw.text((train_x + 30, y_offset), "No disruptions", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING_SMALL
        draw.text((train_x + 30, y_offset), "expected.", font=train_font, fill=0)
        y_offset += TRAIN_LINE_SPACING
    elif train_info:
        for disruption in train_info['disruptions']:
            draw_mdi_icon(draw_r, train_x, y_offset, MDI.ALERT_CIRCLE, size=20, color=0)

            draw_r.text((train_x + 25, y_offset), f"Line: {disruption['Line']}",
                       font=train_font, fill=0)
            y_offset += TRAIN_LINE_SPACING

            draw.text((train_x + 25, y_offset), f"Dir: {disruption['Direction']}",
                     font=train_font, fill=0)
            y_offset += TRAIN_LINE_SPACING

            stations = ", ".join(disruption['Stations'])
            wrapped_stations = textwrap.wrap(stations, width=TRAIN_WRAP_WIDTH)
            for line in wrapped_stations[:2]:
                draw.text((train_x + 25, y_offset), line, font=get_font(FONT_MEDIUM), fill=0)
                y_offset += TRAIN_STATION_LINE_SPACING

            y_offset += TRAIN_DISRUPTION_GAP

            # Stop if getting too long to leave room for weather (which starts
            # at SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT in the same column)
            if y_offset > SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT:
                break

        if train_info.get('content') and y_offset < SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT + 20:
            y_offset += ALERT_SECTION_GAP
            draw_r.line((train_x, y_offset, SCREEN_WIDTH - SCREEN_MARGIN, y_offset), fill=0, width=1)
            y_offset += ALERT_POST_DIVIDER_GAP

            draw_mdi_icon(draw_r, train_x, y_offset, MDI.ALERT, size=18, color=0)
            draw_r.text((train_x + 22, y_offset), "Alert:", font=get_font(FONT_MEDIUM), fill=0)
            y_offset += TRAIN_LINE_SPACING_SMALL

            wrapped_text = textwrap.wrap(train_info['content'], width=TRAIN_WRAP_WIDTH)
            for line in wrapped_text[:3]:
                draw.text((train_x + 25, y_offset), line, font=get_font(BOTTOM_FONT_SIZE), fill=0)
                y_offset += TRAIN_ALERT_LINE_SPACING

    return y_offset  # Return final position

def display_combined_view(display_mgr, font, bus_info, train_info, weather_info, journey_times=None, manual_refresh=False, mqtt_client=None):
    """Display bus arrivals on left, train disruptions and weather on right."""
    logging.debug("Displaying combined bus, train, and weather info...")

    draw, draw_r = display_mgr.clear_images()

    load_font = get_font(LOAD_FONT_SIZE)
    bus_header_font = get_font_bold(FONT_HEADER)

    mqtt_connected = mqtt_client.connected if mqtt_client else False

    draw_mdi_icon(draw, HEADER_ICON_X, HEADER_ICON_Y, MDI.BUS_MARKER, size=HEADER_ICON_SIZE, color=0)
    draw_timestamp(draw_r, manual=manual_refresh)

    if mqtt_connected:
        draw_mdi_icon(draw_r, SCREEN_WIDTH - 70, SCREEN_HEIGHT - 70, MDI.HOME_AUTOMATION, size=HEADER_ICON_SIZE, color=0)

    draw_r.line((COLUMN_OFFSET, COLUMN_DIVIDER_TOP_Y, COLUMN_OFFSET, SCREEN_HEIGHT - SCREEN_MARGIN),
                fill=0, width=DIVIDER_WIDTH)

    # ========== LEFT COLUMN: BUS ARRIVALS ONLY ==========
    draw_r.text((80, HEADER_TEXT_Y), HEADER_A, font=bus_header_font, fill=0)
    draw_r.line((SCREEN_MARGIN, HEADER_DIVIDER_Y, COLUMN_OFFSET - SCREEN_MARGIN, HEADER_DIVIDER_Y), fill=0, width=1)

    final_bus_y = draw_bus_section(draw, draw_r, bus_info, font, BUS_BOX_Y_OFFSET, load_font, journey_times)

    # ========== RIGHT COLUMN: TRAIN STATUS AND WEATHER ==========
    train_x = COLUMN_OFFSET + TRAIN_COLUMN_INDENT

    # Draw train status
    final_train_y = draw_train_section(draw, draw_r, train_info, train_x)

    # Draw weather below train status in right column
    draw_weather_section_right(draw, draw_r, weather_info, train_x)

    system_health.record_display_update(manual=manual_refresh)

    display_mgr.display()
