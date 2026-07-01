import os
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401 (adds app/ to sys.path)
from web_config_schedule_forms import schedule_from_form, atomic_write_json
from scheduler import SCREEN_NAMES, validate_schedule, detect_overlaps


def make_form():
    return {
        'sleep_screen_start': '21:00', 'sleep_screen_end': '06:00',
        'bus_train_screen_start': '06:30', 'bus_train_screen_end': '08:30',
        'daytime_screen_start': '06:00', 'daytime_screen_end': '22:00',
        'ha_screen_start': '20:00', 'ha_screen_end': '21:00',
    }


class TestScheduleFromForm(unittest.TestCase):
    def test_produces_all_four_screens(self):
        schedule = schedule_from_form(make_form())
        self.assertEqual(set(schedule['screens'].keys()), set(SCREEN_NAMES))

    def test_produces_shape_scheduler_accepts(self):
        schedule = schedule_from_form(make_form())
        self.assertEqual(validate_schedule(schedule), [])

    def test_overlap_detected_through_real_wiring(self):
        # sleep_screen (21:00-06:00) and ha_screen (20:00-21:00) don't overlap
        # here, but bus_train_screen sits inside daytime_screen deliberately.
        schedule = schedule_from_form(make_form())
        warnings = detect_overlaps(schedule)
        self.assertTrue(any('bus_train_screen' in w and 'daytime_screen' in w for w in warnings))

    def test_missing_fields_produce_validation_errors(self):
        schedule = schedule_from_form({})
        errors = validate_schedule(schedule)
        self.assertTrue(errors)


class TestAtomicWriteJson(unittest.TestCase):
    def test_writes_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'schedule_config.json')
            data = schedule_from_form(make_form())
            atomic_write_json(path, data)
            import json
            with open(path) as f:
                written = json.load(f)
            self.assertEqual(written, data)

    def test_temp_file_cleaned_up_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'schedule_config.json')
            with mock.patch('os.replace', side_effect=OSError('simulated failure')):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {'version': 1})
            leftover = [f for f in os.listdir(d) if f.startswith('.schedule_config_')]
            self.assertEqual(leftover, [])


if __name__ == "__main__":
    unittest.main()
