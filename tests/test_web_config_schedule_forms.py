import os
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401 (adds app/ to sys.path)
from web_config_schedule_forms import schedule_from_form, atomic_write_json
from scheduler import SCREEN_NAMES, validate_schedule, detect_overlaps


def make_form(ha_enabled=True):
    form = {
        'sleep_screen_start': '21:00', 'sleep_screen_end': '06:00',
        'bus_train_screen_start': '06:30', 'bus_train_screen_end': '08:30',
        'daytime_screen_start': '06:00', 'daytime_screen_end': '22:00',
        'ha_screen_start': '20:00', 'ha_screen_end': '21:00',
    }
    if ha_enabled:
        # A checked HTML checkbox submits value="true"; an unchecked one is
        # simply absent from the form — schedule_from_form() reads that
        # absence as disabled, matching real browser behavior.
        form['ha_screen_enabled'] = 'true'
    return form


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

    def test_ha_screen_enabled_checkbox_checked(self):
        schedule = schedule_from_form(make_form(ha_enabled=True))
        self.assertTrue(schedule['screens']['ha_screen']['enabled'])

    def test_ha_screen_enabled_checkbox_unchecked(self):
        # An unchecked checkbox is simply absent from the submitted form.
        schedule = schedule_from_form(make_form(ha_enabled=False))
        self.assertFalse(schedule['screens']['ha_screen']['enabled'])

    def test_non_disableable_screens_never_get_an_enabled_key(self):
        schedule = schedule_from_form(make_form())
        for name in ('sleep_screen', 'bus_train_screen', 'daytime_screen'):
            self.assertNotIn('enabled', schedule['screens'][name])


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
