"""Data fetching: LTA bus/train APIs, Home Assistant weather, journey-time
routing (OneMap/Google), plus the shared HTTP session, response cache, and
per-endpoint backoff manager they're all built on.
"""
import json
import logging
from functools import lru_cache
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

    def set(self, key, data):
        self.cache[key] = (data, datetime.now())

    def clear(self):
        """Clear all cached data."""
        self.cache.clear()
        logging.debug("Cache cleared")

cache = DataCache()


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
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
        return []

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

        cached_data = cache.get(cache_key)
        return cached_data if cached_data is not None else []

@lru_cache(maxsize=10)
def get_bus_stop_coordinates(bus_stop_code):
    """Get coordinates for a bus stop code from LTA DataMall."""
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
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
        return "No Disruptions Today!"

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

        cached_data = cache.get(cache_key)
        return cached_data if cached_data is not None else "No Disruptions Today!"

def get_weather_from_homeassistant(force_refresh=False):
    """Fetch weather data from Home Assistant with caching and backoff."""
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN:
        logging.debug("Home Assistant API URL or token not configured")
        return None

    cache_key = "weather_data"

    if not force_refresh and not backoff_manager.should_retry(cache_key):
        if cache_key in cache.cache:
            data, _ = cache.cache[cache_key]
            return data
        return None

    if not force_refresh:
        if cache_key in cache.cache:
            data, timestamp = cache.cache[cache_key]
            if datetime.now() - timestamp < timedelta(seconds=WEATHER_CACHE_DURATION):
                logging.debug(f"Using cached weather data (age: {(datetime.now() - timestamp).seconds}s)")
                return data

    logging.debug("Fetching weather from Home Assistant...")

    url = f"{HOME_ASSISTANT_API_URL}/api/states/{HOME_ASSISTANT_WEATHER_ENTITY}"
    headers = {
        'Authorization': f'Bearer {HOME_ASSISTANT_TOKEN}',
        'Content-Type': 'application/json'
    }

    try:
        response = http_session.get(url, headers=headers, timeout=HTTP_TIMEOUT_DEFAULT)
        response.raise_for_status()
        data = response.json()

        weather = {
            'temperature': data['attributes'].get('temperature'),
            'condition': data['state'],
            'humidity': data['attributes'].get('humidity'),
            'wind_speed': data['attributes'].get('wind_speed'),
            'forecast': data['attributes'].get('forecast', [])
        }

        cache.set(cache_key, weather)
        backoff_manager.reset(cache_key)
        system_health.record_api_call('weather', success=True)
        logging.info(f"Weather updated: {weather['temperature']}°C, {weather['condition']}")
        return weather

    except requests.RequestException as e:
        logging.error(f"Error fetching weather from Home Assistant: {e}")
        backoff_manager.record_failure(cache_key)
        system_health.record_api_call('weather', success=False)

        if cache_key in cache.cache:
            data, timestamp = cache.cache[cache_key]
            logging.warning(f"Using stale weather cache (age: {(datetime.now() - timestamp).seconds}s)")
            return data
        return None

def fetch_data_parallel(force_refresh=False):
    """Fetch bus, train, weather data in parallel, then calculate journey times."""
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_bus = executor.submit(get_bus_arrival, BUS_STOP_CODE_A, force_refresh)
        future_train = executor.submit(get_train_disruptions, force_refresh)
        future_weather = executor.submit(get_weather_from_homeassistant, force_refresh)

        bus_info = future_bus.result()
        train_info = future_train.result()
        weather_info = future_weather.result()

    # Calculate journey times using API (done after bus data is fetched)
    journey_times = {}
    if SHOW_JOURNEY_TIME and BUS_SERVICES_TO_TRACK:
        journey_times = calculate_journey_times_with_api(bus_info, BUS_SERVICES_TO_TRACK)

    return bus_info, train_info, weather_info, journey_times
