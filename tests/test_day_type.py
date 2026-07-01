import unittest
from datetime import date

import tests  # noqa: F401 (adds app/ to sys.path)
from day_type import resolve_day_type, DayTypeCache, resolve_todays_day_type


class TestResolveDayType(unittest.TestCase):
    def test_school_day_on_wins(self):
        self.assertEqual(resolve_day_type('on', 'on'), 'school_day')
        self.assertEqual(resolve_day_type('on', 'off'), 'school_day')

    def test_workday_on_when_not_school_day(self):
        self.assertEqual(resolve_day_type('off', 'on'), 'work_day')

    def test_off_day_when_neither_on(self):
        self.assertEqual(resolve_day_type('off', 'off'), 'off_day')

    def test_unavailable_states_treated_as_not_on(self):
        self.assertEqual(resolve_day_type('unavailable', 'unavailable'), 'off_day')

    def test_both_none_returns_fallback(self):
        self.assertEqual(resolve_day_type(None, None, fallback='work_day'), 'work_day')
        self.assertEqual(resolve_day_type(None, None, fallback='school_day'), 'school_day')


class TestDayTypeCache(unittest.TestCase):
    def test_resolves_once_per_calendar_date(self):
        cache = DayTypeCache()
        calls = []

        def resolver():
            calls.append(1)
            return 'school_day'

        today = date(2026, 1, 5)
        cache.get_or_resolve(resolver, today=today)
        cache.get_or_resolve(resolver, today=today)
        self.assertEqual(len(calls), 1)

    def test_reresolves_on_date_change(self):
        cache = DayTypeCache()
        calls = []

        def resolver():
            calls.append(1)
            return 'off_day'

        cache.get_or_resolve(resolver, today=date(2026, 1, 5))
        cache.get_or_resolve(resolver, today=date(2026, 1, 6))
        self.assertEqual(len(calls), 2)

    def test_returns_resolved_value(self):
        cache = DayTypeCache()
        result = cache.get_or_resolve(lambda: 'work_day', today=date(2026, 1, 5))
        self.assertEqual(result, 'work_day')


class TestResolveTodaysDayType(unittest.TestCase):
    def test_uses_sensor_fetch_and_resolves(self):
        cache = DayTypeCache()

        def fake_get_sensors():
            return ('on', 'off')

        result = resolve_todays_day_type(cache, fake_get_sensors, fallback='work_day')
        self.assertEqual(result, 'school_day')

    def test_falls_back_to_previous_day_type_when_ha_unreachable(self):
        cache = DayTypeCache()
        cache._day_type = 'school_day'
        cache._resolved_date = date(2026, 1, 4)

        def fake_get_sensors():
            return (None, None)

        result = resolve_todays_day_type(cache, fake_get_sensors, fallback='off_day')
        # cache._day_type from yesterday ('school_day') is used as the
        # fallback in preference to the config-level fallback ('off_day')
        self.assertEqual(result, 'school_day')


if __name__ == "__main__":
    unittest.main()
