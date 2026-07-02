import unittest
from datetime import datetime, time

import tests  # noqa: F401 (adds app/ to sys.path)
from scheduler import (
    validate_schedule,
    default_schedule_from_env,
    detect_overlaps,
    resolve_active_screen,
    get_next_wake_time,
    parse_hhmm,
    ScheduleConfigError,
)


def make_schedule(sleep=("21:00", "06:00"), ha=("20:00", "21:00"), bus=("06:30", "08:30"), daytime=("06:00", "22:00")):
    return {
        "version": 1,
        "screens": {
            "sleep_screen": {"start": sleep[0], "end": sleep[1]},
            "ha_screen": {"start": ha[0], "end": ha[1]},
            "bus_train_screen": {"start": bus[0], "end": bus[1]},
            "daytime_screen": {"start": daytime[0], "end": daytime[1]},
        },
    }


class TestParseHHMM(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_hhmm("06:30"), time(6, 30))

    def test_invalid_raises(self):
        with self.assertRaises(ScheduleConfigError):
            parse_hhmm("not-a-time")


class TestValidateSchedule(unittest.TestCase):
    def test_valid_schedule_has_no_errors(self):
        self.assertEqual(validate_schedule(make_schedule()), [])

    def test_missing_screens_key(self):
        errors = validate_schedule({})
        self.assertTrue(errors)

    def test_missing_required_screen(self):
        schedule = make_schedule()
        del schedule["screens"]["daytime_screen"]
        errors = validate_schedule(schedule)
        self.assertTrue(any("daytime_screen" in e for e in errors))

    def test_missing_sleep_screen_is_required(self):
        schedule = make_schedule()
        del schedule["screens"]["sleep_screen"]
        errors = validate_schedule(schedule)
        self.assertTrue(any("sleep_screen" in e for e in errors))

    def test_bad_hhmm(self):
        schedule = make_schedule(ha=("garbage", "06:00"))
        errors = validate_schedule(schedule)
        self.assertTrue(any("ha_screen" in e for e in errors))

    def test_start_equals_end(self):
        schedule = make_schedule(daytime=("06:00", "06:00"))
        errors = validate_schedule(schedule)
        self.assertTrue(any("daytime_screen" in e for e in errors))


class TestDefaultScheduleFromEnv(unittest.TestCase):
    def test_produces_valid_schedule(self):
        schedule = default_schedule_from_env(7, 22)
        self.assertEqual(validate_schedule(schedule), [])

    def test_sleep_screen_is_overnight_complement(self):
        schedule = default_schedule_from_env(7, 22)
        self.assertEqual(schedule["screens"]["sleep_screen"], {"start": "22:00", "end": "07:00"})

    def test_ha_screen_gets_hour_before_sleep(self):
        schedule = default_schedule_from_env(7, 22)
        self.assertEqual(schedule["screens"]["ha_screen"], {"start": "21:00", "end": "22:00"})


class TestDetectOverlaps(unittest.TestCase):
    def test_bus_train_inside_daytime_is_reported(self):
        warnings = detect_overlaps(make_schedule())
        self.assertTrue(any("bus_train_screen" in w and "daytime_screen" in w for w in warnings))

    def test_ha_inside_daytime_is_reported(self):
        schedule = make_schedule(ha=("21:00", "22:00"), daytime=("06:00", "22:00"))
        warnings = detect_overlaps(schedule)
        self.assertTrue(any("ha_screen" in w and "daytime_screen" in w for w in warnings))

    def test_no_overlap_when_windows_disjoint(self):
        schedule = make_schedule(sleep=("23:00", "23:59"), ha=("21:00", "22:00"), bus=("06:30", "08:30"), daytime=("09:00", "21:00"))
        self.assertEqual(detect_overlaps(schedule), [])


class TestGetNextWakeTime(unittest.TestCase):
    def test_returns_sleep_screen_end(self):
        schedule = make_schedule(sleep=("21:00", "06:30"))
        self.assertEqual(get_next_wake_time(schedule), "06:30")


class TestResolveActiveScreen(unittest.TestCase):
    def setUp(self):
        self.schedule = make_schedule()

    def test_mid_morning_school_day_shows_bus_train(self):
        now = datetime(2026, 1, 5, 7, 0)  # 07:00
        screen = resolve_active_screen(self.schedule, "school_day", now)
        self.assertEqual(screen, "bus_train_screen")

    def test_mid_morning_work_day_falls_back_to_daytime(self):
        now = datetime(2026, 1, 5, 7, 0)
        screen = resolve_active_screen(self.schedule, "work_day", now)
        self.assertEqual(screen, "daytime_screen")

    def test_mid_morning_off_day_falls_back_to_daytime(self):
        now = datetime(2026, 1, 5, 7, 0)
        screen = resolve_active_screen(self.schedule, "off_day", now)
        self.assertEqual(screen, "daytime_screen")

    def test_overnight_shows_sleep_screen_regardless_of_day_type(self):
        now = datetime(2026, 1, 5, 23, 0)
        for day_type in ("school_day", "work_day", "off_day"):
            screen = resolve_active_screen(self.schedule, day_type, now)
            self.assertEqual(screen, "sleep_screen")

    def test_early_morning_wraparound_shows_sleep_screen(self):
        now = datetime(2026, 1, 5, 3, 0)  # 03:00, within 21:00-06:00 wrap
        screen = resolve_active_screen(self.schedule, "school_day", now)
        self.assertEqual(screen, "sleep_screen")

    def test_ha_screen_shows_in_a_gap_no_other_screen_covers(self):
        # ha_screen is lowest precedence — it only shows when sleep_screen,
        # bus_train_screen, and daytime_screen all leave a genuine gap.
        schedule = make_schedule(sleep=("21:00", "06:00"), ha=("19:00", "20:00"), bus=("06:30", "08:30"), daytime=("06:00", "19:00"))
        now = datetime(2026, 1, 5, 19, 30)  # 19:30, only within ha_screen's 19:00-20:00
        screen = resolve_active_screen(schedule, "off_day", now)
        self.assertEqual(screen, "ha_screen")

    def test_sleep_screen_beats_ha_screen_on_overlap(self):
        schedule = make_schedule(sleep=("20:30", "06:00"), ha=("20:00", "21:00"))
        now = datetime(2026, 1, 5, 20, 45)  # inside both sleep_screen and ha_screen
        screen = resolve_active_screen(schedule, "school_day", now)
        self.assertEqual(screen, "sleep_screen")

    def test_gap_between_windows_falls_back_to_daytime(self):
        schedule = make_schedule(sleep=("23:00", "23:59"), ha=("21:00", "22:00"), bus=("06:30", "08:30"), daytime=("09:00", "21:00"))
        now = datetime(2026, 1, 5, 5, 0)  # gap: not in any window
        screen = resolve_active_screen(schedule, "off_day", now)
        self.assertEqual(screen, "daytime_screen")

    def test_bus_train_beats_daytime_on_overlap(self):
        now = datetime(2026, 1, 5, 7, 30)  # inside both bus_train (06:30-08:30) and daytime (06:00-22:00)
        screen = resolve_active_screen(self.schedule, "school_day", now)
        self.assertEqual(screen, "bus_train_screen")

    def test_bus_train_beats_ha_screen_on_overlap(self):
        schedule = make_schedule(sleep=("23:00", "23:59"), ha=("06:00", "07:00"), bus=("06:30", "08:30"), daytime=("09:00", "21:00"))
        now = datetime(2026, 1, 5, 6, 45)  # inside both ha_screen and bus_train_screen
        screen = resolve_active_screen(schedule, "school_day", now)
        self.assertEqual(screen, "bus_train_screen")

    def test_daytime_beats_ha_screen_on_overlap(self):
        schedule = make_schedule(sleep=("23:00", "23:59"), ha=("10:00", "11:00"), bus=("06:30", "08:30"), daytime=("09:00", "21:00"))
        now = datetime(2026, 1, 5, 10, 30)  # inside both ha_screen and daytime_screen
        screen = resolve_active_screen(schedule, "off_day", now)
        self.assertEqual(screen, "daytime_screen")


if __name__ == "__main__":
    unittest.main()
