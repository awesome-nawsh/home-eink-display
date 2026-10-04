"""Fetcher robustness tests: malformed-but-200 API responses degrade to the
normal failure path (backoff + stale data) instead of raising out of the
fetch thread, the backoff timer survives day-long gaps, and the LTA URL /
bus-stop lookup handling. No network — http_session.get is always mocked.
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import tests  # noqa: F401 (adds app/ to sys.path)
import fetchers


def fake_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


class FetcherTestCase(unittest.TestCase):
    def setUp(self):
        # Fresh singletons so tests don't see each other's (or a real run's) state
        patchers = [
            patch.object(fetchers, 'cache', fetchers.DataCache()),
            patch.object(fetchers, 'backoff_manager', fetchers.BackoffManager()),
            patch.dict(fetchers._bus_stop_coordinates_memo, clear=True),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)


class TestMalformedResponses(FetcherTestCase):
    def test_bus_missing_field_is_a_failure_not_a_crash(self):
        payload = {"Services": [{"ServiceNo": "12",
                                 "NextBus": {"EstimatedArrival": "2026-10-03T10:00:00+08:00"}}]}  # no "Load"
        with patch.object(fetchers.http_session, 'get', return_value=fake_response(payload)):
            self.assertIsNone(fetchers.get_bus_arrival('12345', force_refresh=True))
        self.assertIn('bus_12345', fetchers.backoff_manager.failures)

    def test_bus_malformed_serves_stale_data(self):
        fetchers.cache.set('bus_12345', [('12', [3], ['SEA'])])
        with patch.object(fetchers.http_session, 'get', return_value=fake_response({"Services": "garbage"})):
            self.assertEqual(fetchers.get_bus_arrival('12345', force_refresh=True), [('12', [3], ['SEA'])])

    def test_train_wrong_shape_is_a_failure_not_a_crash(self):
        with patch.object(fetchers.http_session, 'get', return_value=fake_response({"value": []})):
            self.assertIsNone(fetchers.get_train_disruptions(force_refresh=True))
        self.assertIn('train_disruptions', fetchers.backoff_manager.failures)

    def test_ha_weather_missing_attributes_returns_none(self):
        with patch.object(fetchers, 'HOME_ASSISTANT_API_URL', 'http://ha'), \
             patch.object(fetchers, 'HOME_ASSISTANT_TOKEN', 't'), \
             patch.object(fetchers.http_session, 'get', return_value=fake_response({"state": "sunny"})):
            self.assertIsNone(fetchers._fetch_weather_ha())

    def test_day_type_missing_state_returns_none_pair(self):
        with patch.object(fetchers, 'HOME_ASSISTANT_API_URL', 'http://ha'), \
             patch.object(fetchers, 'HOME_ASSISTANT_TOKEN', 't'), \
             patch.object(fetchers.http_session, 'get', return_value=fake_response({})):
            self.assertEqual(fetchers.get_day_type_sensors(), (None, None))


class TestBackoffTiming(unittest.TestCase):
    def test_failure_older_than_a_day_is_retried(self):
        # timedelta.seconds wraps at 24h, so a day-old failure used to look
        # 5 seconds old and stay in backoff
        b = fetchers.BackoffManager()
        b.failures['k'] = (0, datetime.now() - timedelta(days=1, seconds=5))
        self.assertTrue(b.should_retry('k'))

    def test_recent_failure_still_backs_off(self):
        b = fetchers.BackoffManager()
        b.failures['k'] = (0, datetime.now() - timedelta(seconds=5))
        self.assertFalse(b.should_retry('k'))


class TestLtaUrls(FetcherTestCase):
    def test_base_url_strips_legacy_query(self):
        self.assertEqual(fetchers._lta_base_url('https://x/v3/BusArrival?BusStopCode='), 'https://x/v3/BusArrival')
        self.assertEqual(fetchers._lta_base_url('https://x/v3/BusArrival'), 'https://x/v3/BusArrival')

    def test_bus_arrival_sends_stop_code_as_param(self):
        for configured in ('https://x/v3/BusArrival', 'https://x/v3/BusArrival?BusStopCode='):
            with patch.object(fetchers, 'BUS_API_URL', configured), \
                 patch.object(fetchers.http_session, 'get',
                              return_value=fake_response({"Services": []})) as get:
                self.assertEqual(fetchers.get_bus_arrival('12345', force_refresh=True), [])
            self.assertEqual(get.call_args.args[0], 'https://x/v3/BusArrival')
            self.assertEqual(get.call_args.kwargs['params'], {'BusStopCode': '12345'})


class TestBusStopCoordinates(FetcherTestCase):
    def test_filtered_response(self):
        payload = {"value": [{"BusStopCode": "12345", "Latitude": 1.3, "Longitude": 103.8}]}
        with patch.object(fetchers.http_session, 'get', return_value=fake_response(payload)):
            self.assertEqual(fetchers.get_bus_stop_coordinates('12345'), (1.3, 103.8))

    def test_ignored_filter_does_not_return_first_stop(self):
        # If LTA ignores the filter, value[0] is just the first stop in its
        # dataset — the lookup must page on until the right code turns up.
        page1 = {"value": [{"BusStopCode": f"{i:05d}", "Latitude": 0, "Longitude": 0} for i in range(500)]}
        page2 = {"value": [{"BusStopCode": "99999", "Latitude": 0, "Longitude": 0},
                           {"BusStopCode": "12345x", "Latitude": 0, "Longitude": 0},
                           {"BusStopCode": "54321", "Latitude": 1.4, "Longitude": 103.9}]}
        with patch.object(fetchers.http_session, 'get',
                          side_effect=[fake_response(page1), fake_response(page2)]) as get:
            self.assertEqual(fetchers.get_bus_stop_coordinates('54321'), (1.4, 103.9))
        self.assertEqual(get.call_args.kwargs['params'], {'BusStopCode': '54321', '$skip': 500})

    def test_not_found_is_memoized(self):
        with patch.object(fetchers.http_session, 'get', return_value=fake_response({"value": []})) as get:
            self.assertIsNone(fetchers.get_bus_stop_coordinates('00000'))
            self.assertIsNone(fetchers.get_bus_stop_coordinates('00000'))
        self.assertEqual(get.call_count, 1)

    def test_network_failure_is_not_memoized(self):
        import requests
        with patch.object(fetchers.http_session, 'get', side_effect=requests.ConnectionError('down')):
            self.assertIsNone(fetchers.get_bus_stop_coordinates('12345'))
        self.assertNotIn('12345', fetchers._bus_stop_coordinates_memo)


if __name__ == "__main__":
    unittest.main()
