"""Weather tests: the pure WMO-code -> condition mapping, and get_weather()'s
two-source ordering (Home Assistant first, Open-Meteo fallback, stale cache
last). The raw HTTP fetchers themselves are integration-only, same convention
as boot_checks' network probes.
"""
import unittest
from unittest.mock import patch

import tests  # noqa: F401 (adds app/ to sys.path)
import fetchers
from fetchers import map_wmo_code_to_condition, get_weather

HA_WEATHER = {'temperature': 30.1, 'condition': 'partlycloudy',
              'humidity': 75, 'wind_speed': 11.2, 'forecast': []}
OM_WEATHER = {'temperature': 29.5, 'condition': 'rainy',
              'humidity': 80, 'wind_speed': 9.0, 'forecast': []}


class TestWmoMapping(unittest.TestCase):
    def test_clear(self):
        self.assertEqual(map_wmo_code_to_condition(0), 'sunny')
        self.assertEqual(map_wmo_code_to_condition(0, is_day=False), 'clear-night')

    def test_partly_cloudy(self):
        for code in (1, 2):
            self.assertEqual(map_wmo_code_to_condition(code), 'partlycloudy')

    def test_overcast_and_fog(self):
        for code in (3, 45, 48):
            self.assertEqual(map_wmo_code_to_condition(code), 'cloudy')

    def test_rain_family(self):
        for code in (51, 55, 61, 65, 67, 80, 82, 95, 96, 99):
            self.assertEqual(map_wmo_code_to_condition(code), 'rainy')

    def test_snow_family(self):
        for code in (71, 75, 77, 85, 86):
            self.assertEqual(map_wmo_code_to_condition(code), 'snowy')

    def test_unknown_code_defaults(self):
        self.assertEqual(map_wmo_code_to_condition(42), 'partlycloudy')
        self.assertEqual(map_wmo_code_to_condition(None), 'partlycloudy')


class TestGetWeatherSourceOrdering(unittest.TestCase):
    def setUp(self):
        # Fresh cache/backoff singletons so tests don't see each other's
        # (or a real run's) state; PSI fetch stubbed out so no test ever
        # touches the network.
        fetchers.cache = fetchers.DataCache()
        fetchers.backoff_manager = fetchers.BackoffManager()
        psi_patcher = patch.object(fetchers, '_fetch_psi', return_value=57)
        psi_patcher.start()
        self.addCleanup(psi_patcher.stop)

    def test_ha_success_wins_and_skips_openmeteo(self):
        with patch.object(fetchers, '_fetch_weather_ha', return_value=dict(HA_WEATHER)), \
             patch.object(fetchers, '_fetch_weather_openmeteo') as om:
            self.assertEqual(get_weather(force_refresh=True), dict(HA_WEATHER, psi=57))
            om.assert_not_called()

    def test_ha_none_falls_back_to_openmeteo(self):
        with patch.object(fetchers, '_fetch_weather_ha', return_value=None), \
             patch.object(fetchers, '_fetch_weather_openmeteo', return_value=dict(OM_WEATHER)):
            self.assertEqual(get_weather(force_refresh=True), dict(OM_WEATHER, psi=57))

    def test_both_fail_returns_none_when_no_cache(self):
        with patch.object(fetchers, '_fetch_weather_ha', return_value=None), \
             patch.object(fetchers, '_fetch_weather_openmeteo', return_value=None):
            self.assertIsNone(get_weather(force_refresh=True))

    def test_both_fail_serves_stale_cache(self):
        fetchers.cache.set('weather_data', HA_WEATHER)
        # Age the entry past the normal TTL so only the stale path can serve it.
        data, _ = fetchers.cache.cache['weather_data']
        from datetime import datetime, timedelta
        fetchers.cache.cache['weather_data'] = (
            data, datetime.now() - timedelta(seconds=fetchers.WEATHER_CACHE_DURATION + 60))

        with patch.object(fetchers, '_fetch_weather_ha', return_value=None), \
             patch.object(fetchers, '_fetch_weather_openmeteo', return_value=None):
            self.assertEqual(get_weather(force_refresh=True), HA_WEATHER)

    def test_fresh_cache_short_circuits_fetch(self):
        fetchers.cache.set('weather_data', OM_WEATHER)
        with patch.object(fetchers, '_fetch_weather_ha') as ha, \
             patch.object(fetchers, '_fetch_weather_openmeteo') as om:
            self.assertEqual(get_weather(), OM_WEATHER)
            ha.assert_not_called()
            om.assert_not_called()

    def test_success_resets_backoff_after_failures(self):
        with patch.object(fetchers, '_fetch_weather_ha', return_value=None), \
             patch.object(fetchers, '_fetch_weather_openmeteo', return_value=None):
            get_weather(force_refresh=True)
        with patch.object(fetchers, '_fetch_weather_ha', return_value=dict(HA_WEATHER)), \
             patch.object(fetchers, '_fetch_weather_openmeteo'):
            self.assertEqual(get_weather(force_refresh=True), dict(HA_WEATHER, psi=57))
        self.assertTrue(fetchers.backoff_manager.should_retry('weather_data'))


if __name__ == "__main__":
    unittest.main()
