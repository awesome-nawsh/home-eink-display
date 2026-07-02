"""Data fetching: LTA bus/train APIs, weather (Home Assistant with an
Open-Meteo fallback), journey-time routing (OneMap/Google), plus the shared
HTTP session, response cache, and per-endpoint backoff manager they're all
built on.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import *
from health import system_health

# ============================================================================
# HTTP SESSION WITH RETRY LOGIC
# ============================================================================
def create_session():
    """Create a requests session with retry logic for reliability."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

http_session = create_session()

# ============================================================================
# API FUNCTIONS WITH CACHING
# ============================================================================
class DataCache:
    """Simple cache with expiration for API responses."""
    def __init__(self):
        self.cache = {}

    def get(self, key, duration=CACHE_DURATION):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=duration):
                return data
        return None

    def get_stale(self, key, max_age=None):
        """Ignores the normal TTL: returns (data, age_seconds) even for an
        expired entry, or None if the key is absent or older than `max_age`
        seconds — in which case the entry is also evicted, since data that
        old is no longer worth serving. Used by the fetchers' failure paths
        to serve last-known-good data during an API outage. max_age=None
        means any age is acceptable (weather ages gracefully; bus arrival
        times don't — they get STALE_DATA_MAX_AGE)."""
        if key not in self.cache:
            return None
        data, timestamp = self.cache[key]
        age = (datetime.now() - timestamp).total_seconds()
        if max_age is not None and age > max_age:
            del self.cache[key]
            logging.warning(
                f"Evicted '{key}' from cache — {int(age)}s old, beyond the {max_age}s stale-serving limit"
            )
            return None
        return data, age

    def prune(self, max_age, prefix=None):
        """Evict entries older than `max_age` seconds (optionally only keys
        starting with `prefix`). Journey-time keys embed the departure time,
        so a new key appears every few minutes and would otherwise
        accumulate for the life of the process."""
        cutoff = datetime.now() - timedelta(seconds=max_age)
        expired = [
            key for key, (_, timestamp) in self.cache.items()
            if timestamp < cutoff and (prefix is None or key.startswith(prefix))
        ]
        for key in expired:
            del self.cache[key]
        if expired:
            logging.debug(f"Pruned {len(expired)} expired cache entries")

    def set(self, key, data):
        self.cache[key] = (data, datetime.now())

    def clear(self):
        """Clear all cached data."""
        self.cache.clear()
        logging.debug("Cache cleared")

cache = DataCache()


def _stale_or_unavailable(cache_key, label):
    """Shared failure path for the bus/train fetchers: serve last-known-good
    data (even past its normal TTL) for up to STALE_DATA_MAX_AGE while the
    API is failing, then give up — evict the entry and return None so the
    renderer shows an explicit error instead of badly outdated data.

    None deliberately means "the API is failing", which is distinct from a
    successful-but-empty response (no buses running is real data, rendered
    as an empty section, not an error)."""
    stale = cache.get_stale(cache_key, max_age=STALE_DATA_MAX_AGE)
    if stale is not None:
        data, age = stale
        logging.warning(f"Serving stale {label} data ({int(age)}s old) while the API is failing")
        return data
    logging.error(
        f"No usable {label} data: API failing and nothing cached within {STALE_DATA_MAX_AGE}s "
        f"— the display will show an error for this section"
    )
    return None


class BackoffManager:
    """Manages exponential backoff for failed API calls."""
    def __init__(self):
        self.failures = {}

    def should_retry(self, key):
        """Check if enough time has passed to retry."""
        if key not in self.failures:
            return True

        count, last_time = self.failures[key]
        wait_time = min(60 * (2 ** count), 900)
        elapsed = (datetime.now() - last_time).seconds

        if elapsed > wait_time:
            logging.debug(f"Backoff expired for {key}, retrying (waited {elapsed}s)")
            return True

        logging.debug(f"Backoff active for {key}, waiting {wait_time - elapsed}s more")
        return False

    def record_failure(self, key):
        """Record a failure for exponential backoff."""
        if key not in self.failures:
            self.failures[key] = (0, datetime.now())
            logging.warning(f"First failure recorded for {key}")
        else:
            count, _ = self.failures[key]
            self.failures[key] = (count + 1, datetime.now())
            logging.warning(f"Failure #{count + 1} recorded for {key}")

    def reset(self, key):
        """Reset backoff after successful operation."""
        if key in self.failures:
            del self.failures[key]
            logging.debug(f"Backoff reset for {key}")

backoff_manager = BackoffManager()


def get_bus_arrival(bus_stop_code, force_refresh=False):
    """Fetch bus arrival information with caching and backoff."""
    cache_key = f"bus_{bus_stop_code}"

    if not force_refresh and not backoff_manager.should_retry(cache_key):
        return _stale_or_unavailable(cache_key, 'bus')

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            logging.debug(f"Using cached data for bus stop {bus_stop_code}")
            return cached_data

    logging.debug(f"Fetching bus info for stop {bus_stop_code}")

    url = BUS_API_URL + bus_stop_code
    headers = {
        'AccountKey': API_KEY,
        'accept': 'application/json'
    }

    try:
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        data = response.json()

        services = data.get("Services", [])
        bus_info = []

        for service in services:
            service_no = service["ServiceNo"]
            arrival_times = []
            load_rates = []

            for bus in ["NextBus", "NextBus2", "NextBus3"]:
                if service.get(bus) and service[bus].get("EstimatedArrival"):
                    eta = service[bus]["EstimatedArrival"]
                    load = service[bus]["Load"]
                    eta_time = datetime.strptime(eta, "%Y-%m-%dT%H:%M:%S%z")
                    time_diff = (eta_time - datetime.now(eta_time.tzinfo)).total_seconds() / 60
                    arrival_times.append(round(time_diff))
                    load_rates.append(load)

            if arrival_times:
                bus_info.append((service_no, arrival_times, load_rates))

        cache.set(cache_key, bus_info)
        backoff_manager.reset(cache_key)
        system_health.record_api_call('bus', success=True)
        return bus_info

    except requests.RequestException as e:
        logging.error(f"Error fetching bus data for {bus_stop_code}: {e}")
        backoff_manager.record_failure(cache_key)
        system_health.record_api_call('bus', success=False)
        return _stale_or_unavailable(cache_key, 'bus')

# Success-only memo (not lru_cache): coordinates never change for a given
# stop code, so a successful lookup is cached for the life of the process —
# but a failed lookup (transient network blip) must NOT be memoized, or
# journey times would stay dead until a service restart.
_bus_stop_coordinates_memo = {}


def get_bus_stop_coordinates(bus_stop_code):
    """Get coordinates for a bus stop code from LTA DataMall."""
    if bus_stop_code in _bus_stop_coordinates_memo:
        return _bus_stop_coordinates_memo[bus_stop_code]

    # Use the configurable URL
    url = API_BUS_STOP_INFO_URL + bus_stop_code

    headers = {
        'AccountKey': API_KEY,
        'accept': 'application/json'
    }

    try:
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_LONG)
        response.raise_for_status()
        data = response.json()

        # The API returns filtered results when using BusStopCode parameter
        if data.get('value'):
            stop = data['value'][0]  # Should only return one result
            lat = stop['Latitude']
            lon = stop['Longitude']
            logging.info(f"Bus stop {bus_stop_code} coordinates: {lat}, {lon}")
            _bus_stop_coordinates_memo[bus_stop_code] = (lat, lon)
            return lat, lon

        logging.warning(f"Bus stop {bus_stop_code} not found in LTA database")
        return None

    except requests.RequestException as e:
        logging.error(f"Error fetching bus stop coordinates: {e}")
        return None

def calculate_journey_time_onemap(origin_lat, origin_lon, destination, departure_time):
    """
    Calculate journey time using OneMap Routing API.

    Args:
        origin_lat: Origin latitude
        origin_lon: Origin longitude
        destination: Destination address (text)
        departure_time: datetime object for departure

    Returns:
        dict with 'duration_mins' and 'arrival_time' or None
    """
    try:
        # First, geocode the destination address
        search_url = "https://www.onemap.gov.sg/api/common/elastic/search"
        search_params = {
            'searchVal': destination,
            'returnGeom': 'Y',
            'getAddrDetails': 'Y'
        }

        # Headers for search (no auth needed for search)
        search_headers = {}

        response = http_session.get(search_url, params=search_params, headers=search_headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        search_data = response.json()

        if not search_data.get('results'):
            logging.error(f"Destination '{destination}' not found in OneMap")
            return None

        # Get first result coordinates
        dest_lat = float(search_data['results'][0]['LATITUDE'])
        dest_lon = float(search_data['results'][0]['LONGITUDE'])

        logging.debug(f"Destination coordinates: {dest_lat}, {dest_lon}")

        # Now get route using OneMap routing (public transport)
        route_url = "https://www.onemap.gov.sg/api/public/routingsvc/route"
        route_params = {
            'start': f"{origin_lat},{origin_lon}",
            'end': f"{dest_lat},{dest_lon}",
            'routeType': 'pt',  # Public transport
            'date': departure_time.strftime('%Y-%m-%d'),
            'time': departure_time.strftime('%H:%M:%S'),
            'mode': 'TRANSIT',
            'maxWalkDistance': 1000
        }

        # Headers for routing - add Authorization if API key is provided
        route_headers = {}
        if ONEMAP_API_KEY:
            route_headers['Authorization'] = ONEMAP_API_KEY
            logging.debug("Using OneMap API key for authentication")

        response = http_session.get(route_url, params=route_params, headers=route_headers, timeout=HTTP_TIMEOUT_LONG)
        response.raise_for_status()
        route_data = response.json()

        # Parse route data
        if route_data.get('plan') and route_data['plan'].get('itineraries'):
            # Get first itinerary (best route)
            itinerary = route_data['plan']['itineraries'][0]
            duration_seconds = itinerary.get('duration', 0)
            duration_mins = int(duration_seconds / 60)

            arrival_time = departure_time + timedelta(seconds=duration_seconds)

            logging.info(f"OneMap route: {duration_mins} minutes, arrive {arrival_time.strftime('%H:%M')}")

            return {
                'duration_mins': duration_mins,
                'arrival_time': arrival_time.strftime('%H:%M')
            }
        else:
            logging.warning("No route found in OneMap response")
            return None

    except requests.RequestException as e:
        logging.error(f"Error calling OneMap API: {e}")
        return None
    except (KeyError, ValueError, IndexError) as e:
        logging.error(f"Error parsing OneMap response: {e}")
        return None

def calculate_journey_time_google(origin_lat, origin_lon, destination, departure_time):
    """
    Calculate journey time using Google Maps Directions API.

    Args:
        origin_lat: Origin latitude
        origin_lon: Origin longitude
        destination: Destination address (text)
        departure_time: datetime object for departure

    Returns:
        dict with 'duration_mins' and 'arrival_time' or None
    """
    try:
        url = "https://maps.googleapis.com/maps/api/directions/json"

        # Convert departure time to Unix timestamp
        departure_timestamp = int(departure_time.timestamp())

        params = {
            'origin': f"{origin_lat},{origin_lon}",
            'destination': destination,
            'mode': 'transit',
            'departure_time': departure_timestamp,
            'key': GOOGLE_MAPS_API_KEY,
            'region': 'sg'
        }

        response = http_session.get(url, params=params, timeout=HTTP_TIMEOUT_LONG)
        response.raise_for_status()
        data = response.json()

        if data['status'] != 'OK':
            logging.error(f"Google Maps API error: {data.get('status')} - {data.get('error_message', '')}")
            return None

        if not data.get('routes'):
            logging.warning("No routes found in Google Maps response")
            return None

        # Get first route
        route = data['routes'][0]
        leg = route['legs'][0]

        duration_seconds = leg['duration']['value']
        duration_mins = int(duration_seconds / 60)

        arrival_time = departure_time + timedelta(seconds=duration_seconds)

        logging.info(f"Google Maps route: {duration_mins} minutes, arrive {arrival_time.strftime('%H:%M')}")

        return {
            'duration_mins': duration_mins,
            'arrival_time': arrival_time.strftime('%H:%M')
        }

    except requests.RequestException as e:
        logging.error(f"Error calling Google Maps API: {e}")
        return None
    except (KeyError, ValueError, IndexError) as e:
        logging.error(f"Error parsing Google Maps response: {e}")
        return None

def calculate_journey_times_with_api(bus_info, services_to_track):
    """
    Calculate journey times using routing API for specified bus services.

    Args:
        bus_info: List of tuples (service_no, arrival_times, load_rates)
        services_to_track: List of service numbers to track

    Returns:
        Dictionary mapping service_no to journey details
    """
    if not SHOW_JOURNEY_TIME or not JOURNEY_DESTINATION:
        return {}

    # bus_info is None when the bus API is failing (see _stale_or_unavailable)
    # and [] when there's genuinely nothing arriving — no journeys either way.
    if not bus_info:
        return {}

    # Journey cache keys embed the departure time, so old ones are
    # write-once garbage — prune them here rather than letting the dict
    # grow for the life of the process.
    cache.prune(JOURNEY_TIME_CACHE_DURATION, prefix='journey_')

    # Get origin coordinates
    origin_coords = get_bus_stop_coordinates(BUS_STOP_CODE_A)
    if not origin_coords:
        logging.error("Could not get origin bus stop coordinates")
        return {}

    origin_lat, origin_lon = origin_coords
    journey_times = {}

    for service_no in services_to_track:
        # Find service in bus data
        origin_service = next((s for s in bus_info if s[0] == service_no), None)

        if not origin_service:
            logging.debug(f"Service {service_no} not found at bus stop")
            continue

        # Get next bus arrival time
        arrival_mins = origin_service[1][0] if origin_service[1] else None

        if arrival_mins is None or arrival_mins < 0:
            logging.debug(f"Invalid arrival time for service {service_no}")
            continue

        # Calculate departure time (now + bus arrival time)
        departure_time = datetime.now() + timedelta(minutes=arrival_mins)

        # Check cache first (with longer duration for journey times)
        cache_key = f"journey_{service_no}_{departure_time.strftime('%H:%M')}"
        cached_result = cache.get(cache_key, duration=JOURNEY_TIME_CACHE_DURATION)

        if cached_result:
            logging.debug(f"Using cached journey time for service {service_no}")
            journey_times[service_no] = cached_result
            continue

        # Call appropriate routing API
        if ROUTING_API_PROVIDER == 'google':
            result = calculate_journey_time_google(origin_lat, origin_lon, JOURNEY_DESTINATION, departure_time)
        else:  # onemap
            result = calculate_journey_time_onemap(origin_lat, origin_lon, JOURNEY_DESTINATION, departure_time)

        if result:
            # Add bus wait time to total
            total_time = arrival_mins + result['duration_mins']
            result['total_time'] = total_time
            result['bus_wait'] = arrival_mins

            journey_times[service_no] = result
            cache.set(cache_key, result)
            system_health.record_api_call('routing', success=True)

            logging.info(f"Service {service_no}: Wait {arrival_mins}min + Travel {result['duration_mins']}min = {total_time}min total (arrive {result['arrival_time']})")
        else:
            system_health.record_api_call('routing', success=False)

    return journey_times

def get_train_disruptions(force_refresh=False):
    """Fetch train disruption information with caching and backoff."""
    cache_key = "train_disruptions"

    if not force_refresh and not backoff_manager.should_retry(cache_key):
        return _stale_or_unavailable(cache_key, 'train')

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            logging.debug("Using cached train disruption data")
            return cached_data

    logging.debug("Fetching train disruptions...")

    url = TRAIN_API_URL
    headers = {
        'AccountKey': API_KEY,
        'accept': 'application/json'
    }

    try:
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        data = response.json()

        disruptions = []
        content = ''

        if 'value' in data:
            if data['value'].get('AffectedSegments'):
                for segment in data['value']['AffectedSegments']:
                    disruption = {
                        'Line': segment.get('Line', ''),
                        'Direction': segment.get('Direction', ''),
                        'Stations': segment.get('Stations', '').split(',')
                    }
                    disruptions.append(disruption)

            if data['value'].get('Message'):
                content = data['value']['Message'][0].get('Content', '')

        result = "No Disruptions Today!" if not disruptions and not content else {
            'disruptions': disruptions,
            'content': content
        }

        cache.set(cache_key, result)
        backoff_manager.reset(cache_key)
        system_health.record_api_call('train', success=True)
        return result

    except requests.RequestException as e:
        logging.error(f"Error fetching train disruptions: {e}")
        backoff_manager.record_failure(cache_key)
        system_health.record_api_call('train', success=False)
        return _stale_or_unavailable(cache_key, 'train')

def map_wmo_code_to_condition(code, is_day=True):
    """Map an Open-Meteo WMO weather code to the condition strings the rest
    of the app already understands (render/common.py's get_weather_icon() and
    the on-screen condition text) — matching Home Assistant's vocabulary so
    both weather sources render identically. Pure, unit-tested."""
    if not isinstance(code, int):  # missing/None weather_code from the API
        return 'partlycloudy'
    if code == 0:
        return 'sunny' if is_day else 'clear-night'
    if code in (1, 2):
        return 'partlycloudy'
    if code == 3 or code in (45, 48):  # overcast, fog
        return 'cloudy'
    if 51 <= code <= 67 or 80 <= code <= 82:  # drizzle, rain, showers
        return 'rainy'
    if 71 <= code <= 77 or code in (85, 86):  # snow (no dedicated icon; falls back to partly-cloudy)
        return 'snowy'
    if 95 <= code <= 99:  # thunderstorms
        return 'rainy'
    return 'partlycloudy'


def _fetch_weather_ha():
    """Raw Home Assistant weather fetch — no caching/backoff (get_weather()
    owns those). Returns the weather dict or None."""
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN:
        logging.debug("Home Assistant API URL or token not configured")
        return None

    url = f"{HOME_ASSISTANT_API_URL}/api/states/{HOME_ASSISTANT_WEATHER_ENTITY}"
    headers = {
        'Authorization': f'Bearer {HOME_ASSISTANT_TOKEN}',
        'Content-Type': 'application/json'
    }

    try:
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        data = response.json()
        return {
            'temperature': data['attributes'].get('temperature'),
            'condition': data['state'],
            'humidity': data['attributes'].get('humidity'),
            'wind_speed': data['attributes'].get('wind_speed'),
            'forecast': data['attributes'].get('forecast', [])
        }
    except requests.RequestException as e:
        logging.error(f"Error fetching weather from Home Assistant: {e}")
        return None


def _fetch_weather_openmeteo():
    """Raw Open-Meteo weather fetch (free, no API key) — the fallback source
    when Home Assistant is unconfigured or failing. No caching/backoff.
    Location: WEATHER_LAT/WEATHER_LON if set, else the bus stop's own
    coordinates. Returns the same dict shape as _fetch_weather_ha() or None."""
    if WEATHER_LAT is not None and WEATHER_LON is not None:
        lat, lon = WEATHER_LAT, WEATHER_LON
    else:
        coords = get_bus_stop_coordinates(BUS_STOP_CODE_A)
        if not coords:
            logging.warning("Open-Meteo fallback skipped - no coordinates available "
                            "(set WEATHER_LAT/WEATHER_LON or check the LTA bus stop lookup)")
            return None
        lat, lon = coords

    try:
        response = http_session.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': lat,
                'longitude': lon,
                'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,is_day',
                'timezone': 'auto',
            },
            timeout=HTTP_TIMEOUT_DEFAULT,
        )
        response.raise_for_status()
        current = response.json()['current']
        return {
            'temperature': current.get('temperature_2m'),
            'condition': map_wmo_code_to_condition(current.get('weather_code'),
                                                   is_day=bool(current.get('is_day', 1))),
            'humidity': current.get('relative_humidity_2m'),
            'wind_speed': current.get('wind_speed_10m'),
            'forecast': []
        }
    except (requests.RequestException, KeyError, TypeError) as e:
        logging.error(f"Error fetching weather from Open-Meteo: {e}")
        return None


def _fetch_aqi_ha():
    """Raw Home Assistant air-quality fetch: the hourly AQI value plus (best
    effort) its category ("Good"/"Moderate"/...). Returns
    {'aqi', 'aqi_label', 'aqi_category'} or None. No caching (get_weather()
    owns that, since air quality rides along inside the weather dict)."""
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN or not HOME_ASSISTANT_AQI_ENTITY:
        return None

    headers = {
        'Authorization': f'Bearer {HOME_ASSISTANT_TOKEN}',
        'Content-Type': 'application/json'
    }

    def fetch_state(entity_id):
        url = f"{HOME_ASSISTANT_API_URL}/api/states/{entity_id}"
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        return response.json()['state']

    try:
        aqi = round(float(fetch_state(HOME_ASSISTANT_AQI_ENTITY)))
    except (requests.RequestException, KeyError, ValueError) as e:
        logging.warning(f"Error fetching AQI from Home Assistant: {e}")
        return None

    category = None
    if HOME_ASSISTANT_AQI_CATEGORY_ENTITY:
        try:
            state = fetch_state(HOME_ASSISTANT_AQI_CATEGORY_ENTITY)
            if state not in ('unknown', 'unavailable', ''):
                category = state
        except (requests.RequestException, KeyError) as e:
            logging.warning(f"Error fetching AQI category from Home Assistant: {e}")

    return {'aqi': aqi, 'aqi_label': 'AQI', 'aqi_category': category}


def _fetch_psi():
    """Raw NEA 24-hour PSI fetch (data.gov.sg, free, no API key). Returns the
    WORST of the five regional readings — the conservative number for "should
    we play outside" — or None."""
    try:
        response = http_session.get('https://api.data.gov.sg/v1/environment/psi',
                                    timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        readings = response.json()['items'][0]['readings']['psi_twenty_four_hourly']
        return max(readings.values()) if readings else None
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        logging.warning(f"Error fetching PSI from NEA: {e}")
        return None


def _fetch_air_quality():
    """Air quality with the same two-source shape as weather: the user's own
    Home Assistant AQI sensors first, then NEA's public PSI. Returns
    {'aqi', 'aqi_label', 'aqi_category'} or None."""
    ha = _fetch_aqi_ha()
    if ha is not None:
        return ha
    psi = _fetch_psi()
    if psi is not None:
        return {'aqi': psi, 'aqi_label': 'PSI', 'aqi_category': None}
    return None


def get_weather(force_refresh=False):
    """Weather with caching, backoff, and a two-source chain: Home Assistant
    first (skipped when unconfigured), then Open-Meteo. A backoff failure is
    recorded only when BOTH sources fail; either source succeeding resets it.
    (Side effect: while HA is down but Open-Meteo works, HA is retried on
    every refresh rather than backing off — harmless at the ~30-min weather
    cadence.)"""
    cache_key = "weather_data"

    # Weather's failure paths use get_stale() with no max_age — unlike bus
    # arrival times, a weather reading ages gracefully, so last-known-good
    # is served indefinitely during an outage rather than erroring out.
    if not force_refresh and not backoff_manager.should_retry(cache_key):
        stale = cache.get_stale(cache_key)
        return stale[0] if stale else None

    if not force_refresh:
        cached_data = cache.get(cache_key, duration=WEATHER_CACHE_DURATION)
        if cached_data is not None:
            logging.debug("Using cached weather data")
            return cached_data

    weather = _fetch_weather_ha()
    source = 'Home Assistant'
    if weather is None:
        weather = _fetch_weather_openmeteo()
        source = 'Open-Meteo'

    if weather is not None:
        # Air quality rides along in the weather dict (cached and refreshed
        # together) — an air-quality fetch failure just means no reading
        # shown, never a weather failure.
        weather.update(_fetch_air_quality() or {})
        cache.set(cache_key, weather)
        backoff_manager.reset(cache_key)
        system_health.record_api_call('weather', success=True)
        logging.info(f"Weather updated via {source}: "
                     f"{weather['temperature']}°C, {weather['condition']}")
        return weather

    backoff_manager.record_failure(cache_key)
    system_health.record_api_call('weather', success=False)

    stale = cache.get_stale(cache_key)
    if stale:
        data, age = stale
        logging.warning(f"Using stale weather cache (age: {int(age)}s)")
        return data
    return None

def get_day_type_sensors():
    """Fetch binary_sensor.school_day and binary_sensor.workday_sensor raw
    states from Home Assistant. Fetch-only — day_type.py's resolve_day_type()
    turns these into 'school_day'/'work_day'/'off_day'. Returns (None, None)
    if HA isn't configured or unreachable; caller decides the fallback.

    No caching here — day_type.DayTypeCache already resolves this once per
    calendar day, so an extra TTL-based cache in fetchers.py would just add
    a second layer of staleness for no benefit.
    """
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN:
        logging.debug("Home Assistant API URL or token not configured - day-type resolution unavailable")
        return None, None

    headers = {
        'Authorization': f'Bearer {HOME_ASSISTANT_TOKEN}',
        'Content-Type': 'application/json'
    }

    def fetch_state(entity_id):
        url = f"{HOME_ASSISTANT_API_URL}/api/states/{entity_id}"
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        return response.json()['state']

    try:
        school_day_state = fetch_state(HOME_ASSISTANT_SCHOOL_DAY_ENTITY)
        workday_state = fetch_state(HOME_ASSISTANT_WORKDAY_ENTITY)
        system_health.record_api_call('day_type', success=True)
        return school_day_state, workday_state
    except requests.RequestException as e:
        logging.error(f"Error fetching day-type sensors from Home Assistant: {e}")
        system_health.record_api_call('day_type', success=False)
        return None, None

# One long-lived pool rather than a fresh ThreadPoolExecutor per tick —
# spawning and joining three threads every 30 seconds is needless churn on
# the Pi Zero W's single core.
_fetch_executor = ThreadPoolExecutor(max_workers=3)


def fetch_data_parallel(force_refresh=False):
    """Fetch bus, train, weather data in parallel, then calculate journey times."""
    future_bus = _fetch_executor.submit(get_bus_arrival, BUS_STOP_CODE_A, force_refresh)
    future_train = _fetch_executor.submit(get_train_disruptions, force_refresh)
    future_weather = _fetch_executor.submit(get_weather, force_refresh)

    bus_info = future_bus.result()
    train_info = future_train.result()
    weather_info = future_weather.result()

    # Calculate journey times using API (done after bus data is fetched)
    journey_times = {}
    if SHOW_JOURNEY_TIME and BUS_SERVICES_TO_TRACK:
        journey_times = calculate_journey_times_with_api(bus_info, BUS_SERVICES_TO_TRACK)

    return bus_info, train_info, weather_info, journey_times
