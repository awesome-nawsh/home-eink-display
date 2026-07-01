"""Day-type resolution: school_day / work_day / off_day, resolved once per
calendar day (not re-checked continuously) so a sensor flip mid-morning
doesn't yank the active screen away mid-day. Only school_day currently
changes screen selection (bus_train_screen is gated on it in scheduler.py);
distinguishing work_day from off_day content is deferred (see todo.md).
"""
import logging
from datetime import date


def resolve_day_type(school_day_state, workday_state, fallback='work_day'):
    """Pure. Resolution order: school_day == 'on' -> 'school_day';
    elif workday_state == 'on' -> 'work_day'; else -> 'off_day'.
    If both inputs are None (HA unreachable/not configured), returns
    `fallback` verbatim — the caller passes yesterday's resolved day-type
    or config.DAY_TYPE_FALLBACK."""
    if school_day_state is None and workday_state is None:
        return fallback
    if school_day_state == 'on':
        return 'school_day'
    if workday_state == 'on':
        return 'work_day'
    return 'off_day'


class DayTypeCache:
    """Date-keyed (not TTL-based) cache: resolves once per calendar date,
    re-resolves automatically when date.today() changes. Deliberately a
    different mechanism from fetchers.DataCache (TTL-based) —"once per
    calendar day" is a date boundary, not an elapsed-seconds duration."""
    def __init__(self):
        self._resolved_date = None
        self._day_type = None

    def get_or_resolve(self, resolver_fn, today=None):
        """resolver_fn: zero-arg callable that performs the HA fetch +
        resolve_day_type() call, invoked only if today != self._resolved_date.
        `today` defaults to date.today() but can be injected so tests don't
        depend on the real wall-clock date."""
        today = today or date.today()
        if today != self._resolved_date:
            self._day_type = resolver_fn()
            self._resolved_date = today
            logging.info(f"Day-type resolved for {today}: {self._day_type}")
        return self._day_type


def resolve_todays_day_type(cache, get_day_type_sensors, fallback):
    """Convenience wrapper main.py calls each loop iteration; cheap no-op
    unless the calendar date has rolled over. `get_day_type_sensors` is
    passed in (rather than imported here) so this module doesn't need to
    import fetchers.py, avoiding a fetchers<->day_type import cycle."""
    def _do_resolve():
        school_day_state, workday_state = get_day_type_sensors()
        day_fallback = cache._day_type if cache._day_type is not None else fallback
        return resolve_day_type(school_day_state, workday_state, fallback=day_fallback)
    return cache.get_or_resolve(_do_resolve)


day_type_cache = DayTypeCache()
