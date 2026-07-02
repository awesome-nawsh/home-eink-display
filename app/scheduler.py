"""Four-screen scheduler: pure logic for deciding which of `sleep_screen`,
`bus_train_screen`, `daytime_screen`, or `ha_screen` should be active at a
given moment, given a schedule dict and today's resolved day-type.

Precedence is fixed (not user-configurable): sleep_screen > bus_train_screen >
daytime_screen > ha_screen. sleep_screen is the "ultimate override" — the
true overnight state, never gated by day-type. ha_screen is lowest
precedence — it only shows in a genuine gap the other three don't claim.
bus_train_screen is additionally gated on day_type == 'school_day'.
Loading/validating schedule_config.json is kept in this module too, but
isolated to load_schedule_config() so the resolution functions stay pure and
unit-testable without touching the filesystem.
"""
import json
import logging
from datetime import time

SCREEN_NAMES = ("sleep_screen", "bus_train_screen", "daytime_screen", "ha_screen")
PRECEDENCE = ("sleep_screen", "bus_train_screen", "daytime_screen", "ha_screen")

# Friendly labels for the web UI — SCREEN_NAMES stay the on-disk/config
# identifiers (schedule_config.json keys, FORCE_SCREEN values); these are
# purely cosmetic and never compared against or written anywhere.
SCREEN_DISPLAY_NAMES = {
    "sleep_screen": "Overnight (Sleep Screen)",
    "bus_train_screen": "Bus & Train",
    "daytime_screen": "Daytime Clock",
    "ha_screen": "Home Assistant Dashboard",
}

# Screens the web UI lets the user fully switch off. Deliberately just
# ha_screen: sleep_screen is the always-on overnight override, bus_train_screen
# is the primary daytime content, and daytime_screen is resolve_active_screen()'s
# final fallback for any moment none of the others claim — disabling any of
# those three would break the "always something on screen" invariant.
DISABLEABLE_SCREENS = ("ha_screen",)


class ScheduleConfigError(ValueError):
    """Raised by validate_schedule() when the schedule dict is malformed."""


def parse_hhmm(value):
    """'HH:MM' -> datetime.time. Raises ScheduleConfigError on bad format."""
    try:
        hour_str, minute_str = value.split(":")
        return time(int(hour_str), int(minute_str))
    except (AttributeError, ValueError):
        raise ScheduleConfigError(f"Invalid HH:MM time string: {value!r}")


def _minutes(t):
    return t.hour * 60 + t.minute


def _window_ranges(start, end):
    """A window's minute-of-day range(s), handling overnight wraparound.
    Returns a list of (start_min, end_min) half-open ranges, either one
    (same-day window) or two (wraps past midnight)."""
    s, e = _minutes(start), _minutes(end)
    if s < e:
        return [(s, e)]
    return [(s, 1440), (0, e)]


def _ranges_overlap(ranges_a, ranges_b):
    for a_start, a_end in ranges_a:
        for b_start, b_end in ranges_b:
            if a_start < b_end and b_start < a_end:
                return True
    return False


def _time_in_window(now_time, start, end):
    now_min = _minutes(now_time)
    return any(s <= now_min < e for s, e in _window_ranges(start, end))


def validate_schedule(schedule):
    """Pure validation. Returns a list of human-readable error strings
    (empty list = valid)."""
    errors = []
    if not isinstance(schedule, dict) or "screens" not in schedule:
        return ["schedule is missing the top-level 'screens' key"]

    screens = schedule["screens"]
    for name in SCREEN_NAMES:
        if name not in screens:
            errors.append(f"schedule.screens is missing required screen '{name}'")
            continue
        window = screens[name]
        if "start" not in window or "end" not in window:
            errors.append(f"screens.{name} must have 'start' and 'end'")
            continue
        try:
            start = parse_hhmm(window["start"])
            end = parse_hhmm(window["end"])
        except ScheduleConfigError as e:
            errors.append(f"screens.{name}: {e}")
            continue
        if start == end:
            errors.append(f"screens.{name}: start and end must not be equal")

    return errors


def default_schedule_from_env(wake_hour, sleep_hour):
    """Build a minimal schedule dict from legacy WAKE_HOUR/SLEEP_HOUR env
    vars, used when schedule_config.json is absent or invalid.

    sleep_screen takes the overnight complement of the wake window (this is
    now the "ultimate override" state that used to belong to ha_screen).
    ha_screen gets a one-hour slot immediately before sleep_screen starts —
    a deterministic default derived from the same two legacy hours, since
    the old env vars have no dedicated ha_screen window. Because ha_screen
    is lowest precedence, this default slot sits entirely inside
    daytime_screen's window and is fully overridden by it out of the box —
    reconfigure schedule_config.json if you want ha_screen to actually show
    with these defaults (e.g. narrow daytime_screen's window to leave it a
    gap). bus_train_screen and daytime_screen both get the full wake window,
    preserving pre-Phase-2 behavior until the user opts into a real
    schedule_config.json.
    """
    wake = f"{wake_hour:02d}:00"
    sleep = f"{sleep_hour:02d}:00"
    ha_start_hour = (sleep_hour - 1) % 24
    ha_start = f"{ha_start_hour:02d}:00"
    return {
        "version": 1,
        "screens": {
            "sleep_screen": {"start": sleep, "end": wake},
            "ha_screen": {"start": ha_start, "end": sleep},
            "bus_train_screen": {"start": wake, "end": sleep},
            "daytime_screen": {"start": wake, "end": sleep},
        },
    }


def load_schedule_config(path, wake_hour_fallback, sleep_hour_fallback):
    """File I/O boundary. Reads JSON at `path`; on FileNotFoundError,
    JSON decode error, or validation failure, logs a warning and returns
    default_schedule_from_env(...). Never raises — always returns a usable,
    already-validated schedule dict."""
    try:
        with open(path) as f:
            schedule = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"Could not read schedule_config.json at {path} ({e}); using WAKE_HOUR/SLEEP_HOUR defaults")
        return default_schedule_from_env(wake_hour_fallback, sleep_hour_fallback)

    errors = validate_schedule(schedule)
    if errors:
        for error in errors:
            logging.warning(f"schedule_config.json invalid: {error}")
        logging.warning("Falling back to a schedule derived from WAKE_HOUR/SLEEP_HOUR")
        return default_schedule_from_env(wake_hour_fallback, sleep_hour_fallback)

    return schedule


def _screen_enabled(window):
    """A screen without an 'enabled' key (the common case — only
    DISABLEABLE_SCREENS ever get one written) is always enabled."""
    return window.get("enabled", True)


def detect_overlaps(schedule):
    """Pure. Pairwise overlap check across the 4 named screens' windows.
    Overlap is expected/allowed (resolved at runtime by precedence in
    resolve_active_screen) — this just returns human-readable warning
    strings describing what got overridden, for logging. A disabled screen
    is skipped entirely — it can't override or be overridden."""
    screens = schedule["screens"]
    windows = {}
    for name in SCREEN_NAMES:
        w = screens[name]
        if not _screen_enabled(w):
            continue
        windows[name] = _window_ranges(parse_hhmm(w["start"]), parse_hhmm(w["end"]))

    warnings = []
    for i, higher in enumerate(PRECEDENCE):
        if higher not in windows:
            continue
        for lower in PRECEDENCE[i + 1:]:
            if lower not in windows:
                continue
            if _ranges_overlap(windows[higher], windows[lower]):
                warnings.append(
                    f"{higher} schedule overlaps {lower} schedule; {higher} takes precedence"
                )
    return warnings


def get_next_wake_time(schedule):
    """Pure. Returns sleep_screen's configured 'end' time (HH:MM string) —
    the moment the overnight window closes and the lower-priority screens
    stop being pre-empted by it. Used to show "Next wake: HH:MM" on the
    sleep screen without needing to simulate the full precedence chain for
    every later time of day."""
    return schedule["screens"]["sleep_screen"]["end"]


def resolve_active_screen(schedule, day_type, now):
    """Pure. Returns one of 'sleep_screen', 'bus_train_screen',
    'daytime_screen', 'ha_screen'. Overlap warnings are NOT computed here —
    they only change when the schedule changes, so callers run
    detect_overlaps() once per load_schedule_config(), not per tick.

    1. If now falls within sleep_screen's window -> 'sleep_screen' (ultimate
       override — always wins, regardless of day_type).
    2. Elif day_type == 'school_day' and now falls within bus_train_screen's
       window -> 'bus_train_screen'.
    3. Elif now falls within daytime_screen's window -> 'daytime_screen'.
    4. Elif ha_screen is enabled and now falls within its window ->
       'ha_screen' (lowest precedence — only shows in a gap the other
       three don't claim; a disabled ha_screen behaves as if it had no
       window at all, so this step is simply skipped).
    5. Else (a gap none of the four windows cover) -> 'daytime_screen' as
       the safe default, so something is always on screen.
    """
    screens = schedule["screens"]
    now_time = now.time()

    sleep_window = screens["sleep_screen"]
    if _time_in_window(now_time, parse_hhmm(sleep_window["start"]), parse_hhmm(sleep_window["end"])):
        return "sleep_screen"

    bus_train = screens["bus_train_screen"]
    if day_type == "school_day" and _time_in_window(
        now_time, parse_hhmm(bus_train["start"]), parse_hhmm(bus_train["end"])
    ):
        return "bus_train_screen"

    daytime = screens["daytime_screen"]
    if _time_in_window(now_time, parse_hhmm(daytime["start"]), parse_hhmm(daytime["end"])):
        return "daytime_screen"

    ha = screens["ha_screen"]
    if _screen_enabled(ha) and _time_in_window(now_time, parse_hhmm(ha["start"]), parse_hhmm(ha["end"])):
        return "ha_screen"

    return "daytime_screen"
