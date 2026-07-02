"""daytime_screen's pure model: the word clock and the redraw bucket."""
import unittest
from datetime import datetime

import tests  # noqa: F401 (adds app/ to sys.path)
from render.daytime_screen import time_in_words, build_daytime_model

WEATHER = {'temperature': 29, 'condition': 'partlycloudy', 'humidity': 68,
           'wind_speed': 10.0, 'forecast': [],
           'aqi': 57, 'aqi_label': 'AQI', 'aqi_category': 'Moderate'}


class TestTimeInWords(unittest.TestCase):
    def test_quarters(self):
        self.assertEqual(time_in_words(14, 0), "Two o'clock")
        self.assertEqual(time_in_words(14, 1), "Quarter past two")
        self.assertEqual(time_in_words(14, 2), "Half past two")
        self.assertEqual(time_in_words(14, 3), "Quarter to three")

    def test_quarter_to_rolls_the_hour(self):
        self.assertEqual(time_in_words(11, 3), "Quarter to twelve")
        self.assertEqual(time_in_words(23, 3), "Quarter to twelve")
        self.assertEqual(time_in_words(12, 3), "Quarter to one")

    def test_twelve_hour_edge_cases(self):
        self.assertEqual(time_in_words(0, 0), "Twelve o'clock")   # midnight
        self.assertEqual(time_in_words(12, 0), "Twelve o'clock")  # noon
        self.assertEqual(time_in_words(13, 0), "One o'clock")
        self.assertEqual(time_in_words(23, 2), "Half past eleven")


class TestBuildDaytimeModel(unittest.TestCase):
    def test_model_shape(self):
        model = build_daytime_model(datetime(2026, 7, 2, 14, 3), WEATHER)
        self.assertEqual(model['time_words'], "Two o'clock")
        self.assertEqual(model['date'], "Thursday 2 July")
        self.assertEqual(model['weather'], WEATHER)
        self.assertEqual(model['bucket'],
                         ('2026-07-02', 14, 0, (29, 'partlycloudy', 68, 57, 'Moderate')))

    def test_bucket_stable_within_a_quarter(self):
        a = build_daytime_model(datetime(2026, 7, 2, 14, 15), WEATHER)
        b = build_daytime_model(datetime(2026, 7, 2, 14, 29, 59), WEATHER)
        self.assertEqual(a['bucket'], b['bucket'])

    def test_bucket_changes_at_quarter_boundary(self):
        a = build_daytime_model(datetime(2026, 7, 2, 14, 29), WEATHER)
        b = build_daytime_model(datetime(2026, 7, 2, 14, 30), WEATHER)
        self.assertNotEqual(a['bucket'], b['bucket'])
        self.assertEqual(b['time_words'], "Half past two")

    def test_bucket_changes_across_days_at_same_time(self):
        a = build_daytime_model(datetime(2026, 7, 2, 14, 0), WEATHER)
        b = build_daytime_model(datetime(2026, 7, 3, 14, 0), WEATHER)
        self.assertNotEqual(a['bucket'], b['bucket'])

    def test_weather_change_changes_bucket(self):
        warmer = dict(WEATHER, temperature=33)
        a = build_daytime_model(datetime(2026, 7, 2, 14, 0), WEATHER)
        b = build_daytime_model(datetime(2026, 7, 2, 14, 0), warmer)
        self.assertNotEqual(a['bucket'], b['bucket'])

    def test_aqi_change_changes_bucket(self):
        hazier = dict(WEATHER, aqi=105, aqi_category='Unhealthy')
        a = build_daytime_model(datetime(2026, 7, 2, 14, 0), WEATHER)
        b = build_daytime_model(datetime(2026, 7, 2, 14, 0), hazier)
        self.assertNotEqual(a['bucket'], b['bucket'])

    def test_none_weather(self):
        model = build_daytime_model(datetime(2026, 7, 2, 14, 0), None)
        self.assertIsNone(model['weather'])
        self.assertEqual(model['bucket'][3], None)


if __name__ == "__main__":
    unittest.main()
