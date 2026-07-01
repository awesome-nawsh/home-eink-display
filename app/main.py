import sys
import os
import io
import textwrap
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Setting up directories
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import json
from datetime import datetime, timedelta
from waveshare_epd import epd7in5b_V2
import time
from PIL import Image, ImageDraw, ImageFont
import pigpio
import traceback
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
import paho.mqtt.client as mqtt
import atexit
import signal

# Try to import psutil for system monitoring (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available - system monitoring disabled")

# Configure logging based on environment variable
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# CONSTANTS
# ============================================================================
BUS_LOAD_MAP_SIZE = {'SEA': 10, 'SDA': 50, 'LSD': 90}
BUS_LOAD_MAP_TEXT = {'SEA': 'Seats', 'SDA': 'Standing', 'LSD': 'Limited'}

# Display layout constants
COLUMN_WIDTH_RATIO = 0.5
BUS_BOX_HEIGHT = 60
BUS_BOX_WIDTH = 160
BUS_BOX_Y_OFFSET = 70  # y_start for draw_bus_section: 15px below the header divider at y=55
BUS_BOX_Y_SPACING = 105
BUS_NUMBER_FONT_SIZE = 32
LOAD_FONT_SIZE = 16
BOTTOM_FONT_SIZE = 14
BOTTOM_MARGIN = 35
TOP_MARGIN = 20
DIVIDER_WIDTH = 2
WEATHER_SECTION_HEIGHT = 140  # px reserved at the bottom of the right column for weather

# Standard font sizes (consolidated)
FONT_SMALL = 12
FONT_MEDIUM = 16
FONT_LARGE = 24
FONT_XLARGE = 32

# Environment variables with defaults
API_KEY = os.getenv('API_KEY')
BUS_API_URL = os.getenv('API_BUS_URL', 'Not Found - bus API url')
TRAIN_API_URL = os.getenv('API_TRAIN_URL', 'Not Found - train API url')
API_BUS_STOP_INFO_URL = os.getenv('API_BUS_STOP_INFO_URL', 'Not Found - bus stop API url')
HEADER_A = os.getenv('A_HEADER', 'Bus Stop')
BUS_STOP_CODE_A = os.getenv('BUS_STOP_CODE_A')

# Journey Time Configuration - Simplified with API
SHOW_JOURNEY_TIME = os.getenv('SHOW_JOURNEY_TIME', 'false').lower() == 'true'
BUS_SERVICES_TO_TRACK = [s.strip() for s in os.getenv('BUS_SERVICES_TO_TRACK', '').split(',') if s.strip()]
JOURNEY_DESTINATION = os.getenv('JOURNEY_DESTINATION', 'Destination')  # e.g., "School Name, Singapore" or "123 Main St"
JOURNEY_DESTINATION_SHORT = os.getenv('JOURNEY_DESTINATION_SHORT')  # Short name for display (optional)

# Routing API Configuration
ROUTING_API_PROVIDER = os.getenv('ROUTING_API_PROVIDER', 'onemap').lower()  # 'onemap' or 'google'
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')  # Required if using Google
ONEMAP_API_KEY = os.getenv('ONEMAP_API_KEY')  # Optional for OneMap

# Journey time cache (longer duration since routes don't change often)
JOURNEY_TIME_CACHE_DURATION = int(os.getenv('JOURNEY_TIME_CACHE_DURATION', '1800'))  # 30 minutes default

WAKE_HOUR = int(os.getenv('WAKE_HOUR', '7'))
SLEEP_HOUR = int(os.getenv('SLEEP_HOUR', '22'))
WAKE_INTERVAL = int(os.getenv('WAKE_INTERVAL', '30'))
SLEEP_INTERVAL = int(os.getenv('SLEEP_INTERVAL', '300'))
DEBUG_SKIP_TIME_CHECK = os.getenv('DEBUG_SKIP_TIME_CHECK', 'false').lower() == 'true'

# Home Assistant Configuration
HOME_ASSISTANT_API_URL = os.getenv('HOME_ASSISTANT_API_URL')
HOME_ASSISTANT_TOKEN = os.getenv('HOME_ASSISTANT_TOKEN')
HOME_ASSISTANT_WEATHER_ENTITY = os.getenv('HOME_ASSISTANT_WEATHER_ENTITY', 'weather.home')
HOME_ASSISTANT_SLEEP_URL = os.getenv('HOME_ASSISTANT_SLEEP_URL')
SLEEP_SCREEN_DASHBOARD = os.getenv('SLEEP_SCREEN_DASHBOARD')
SLEEP_SCREEN_EINK_MODE = os.getenv('SLEEP_SCREEN_EINK_MODE', '2')
SLEEP_SCREEN_ZOOM = os.getenv('SLEEP_SCREEN_ZOOM', '1')
SLEEP_SCREEN_FORMAT = os.getenv('SLEEP_SCREEN_FORMAT')
SLEEP_SCREEN_WAIT = os.getenv('SLEEP_SCREEN_WAIT', '5000')
SLEEP_SCREEN_THEME = os.getenv('SLEEP_SCREEN_THEME', 'Graphite E-ink Light')

# MQTT Configuration
MQTT_ENABLED = os.getenv('MQTT_ENABLED', 'false').lower() == 'true'
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_TOPIC_REFRESH = os.getenv('MQTT_TOPIC_REFRESH', 'eink/display/refresh')
MQTT_TOPIC_STATUS = os.getenv('MQTT_TOPIC_STATUS', 'eink/display/status')

# Cache duration
CACHE_DURATION = int(os.getenv('CACHE_DURATION', '20'))
WEATHER_CACHE_DURATION = int(os.getenv('WEATHER_CACHE_DURATION', '1800'))

# Global flag for manual refresh
refresh_requested = threading.Event()

# Boot timestamp
boot_timestamp = datetime.now()

# ============================================================================
# UTILITY CLASSES
# ============================================================================
class Watchdog:
    """Monitors main loop health and detects stuck processes."""
    def __init__(self, timeout=300):
        self.timeout = timeout
        self.last_update = datetime.now()
        self.enabled = True
    
    def feed(self):
        """Reset the watchdog timer."""
        self.last_update = datetime.now()
    
    def check(self):
        """Check if watchdog has timed out."""
        if not self.enabled:
            return True
        
        elapsed = (datetime.now() - self.last_update).seconds
        if elapsed > self.timeout:
            logging.error(f"Watchdog timeout! Main loop appears stuck ({elapsed}s since last update)")
            return False
        return True

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

class SystemHealth:
    """Track and report system health metrics."""
    def __init__(self):
        self.metrics = {
            'api_calls': {'bus': 0, 'train': 0, 'weather': 0, 'routing': 0},
            'api_errors': {'bus': 0, 'train': 0, 'weather': 0, 'routing': 0},
            'display_updates': 0,
            'manual_refreshes': 0,
            'last_update': None
        }
    
    def record_api_call(self, api_type, success=True):
        """Record an API call."""
        self.metrics['api_calls'][api_type] += 1
        if not success:
            self.metrics['api_errors'][api_type] += 1
    
    def record_display_update(self, manual=False):
        """Record a display update."""
        self.metrics['display_updates'] += 1
        self.metrics['last_update'] = datetime.now()
        if manual:
            self.metrics['manual_refreshes'] += 1
    
    def get_status(self, mqtt_connected=False, cache_size=0):
        """Get current system status."""
        uptime_seconds = (datetime.now() - boot_timestamp).seconds
        status = {
            'status': 'healthy',
            'uptime_seconds': uptime_seconds,
            'uptime_formatted': str(timedelta(seconds=uptime_seconds)),
            'mqtt_connected': mqtt_connected,
            'cache_size': cache_size,
            'metrics': self.metrics,
            'last_update': self.metrics['last_update'].isoformat() if self.metrics['last_update'] else None
        }
        
        if PSUTIL_AVAILABLE:
            status['memory_percent'] = psutil.virtual_memory().percent
            status['cpu_percent'] = psutil.cpu_percent(interval=0.1)
        
        return status
    
    def log_stats(self):
        """Log current statistics."""
        if PSUTIL_AVAILABLE:
            memory = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            logging.info(f"System: Memory {memory.percent}% | CPU {cpu}%")
        
        logging.info(f"Stats: Display updates: {self.metrics['display_updates']} | "
                    f"API calls - Bus: {self.metrics['api_calls']['bus']}, "
                    f"Train: {self.metrics['api_calls']['train']}, "
                    f"Weather: {self.metrics['api_calls']['weather']}, "
                    f"Routing: {self.metrics['api_calls']['routing']}")

# Initialize utility instances
watchdog = Watchdog(timeout=300)
backoff_manager = BackoffManager()
system_health = SystemHealth()

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
# CONFIGURATION VALIDATION
# ============================================================================
def validate_configuration():
    """Validate critical environment variables on startup."""
    errors = []
    warnings = []
    
    # Critical configuration
    if not API_KEY:
        errors.append("API_KEY is required for bus/train APIs")
    if not BUS_STOP_CODE_A:
        errors.append("BUS_STOP_CODE_A is required")
    if not BUS_API_URL or BUS_API_URL == 'Not Found - bus API url':
        errors.append("API_BUS_URL is not configured")
    if not TRAIN_API_URL or TRAIN_API_URL == 'Not Found - train API url':
        errors.append("API_TRAIN_URL is not configured")
    if not API_BUS_STOP_INFO_URL:
        warnings.append("API_BUS_STOP_INFO_URL not set - using default")
    
    # ... rest of validation
    
    # Journey time configuration
    if SHOW_JOURNEY_TIME:
        if not JOURNEY_DESTINATION:
            warnings.append("SHOW_JOURNEY_TIME enabled but JOURNEY_DESTINATION not set")
        if not BUS_SERVICES_TO_TRACK:
            warnings.append("SHOW_JOURNEY_TIME enabled but BUS_SERVICES_TO_TRACK not set")
        if ROUTING_API_PROVIDER == 'google' and not GOOGLE_MAPS_API_KEY:
            errors.append("Google Maps selected but GOOGLE_MAPS_API_KEY not set")
    
    # Optional but recommended
    if not HOME_ASSISTANT_API_URL:
        warnings.append("HOME_ASSISTANT_API_URL not set - weather disabled")
    if not HOME_ASSISTANT_TOKEN:
        warnings.append("HOME_ASSISTANT_TOKEN not set - weather disabled")
    if MQTT_ENABLED and not MQTT_BROKER:
        warnings.append("MQTT enabled but MQTT_BROKER not set")
    if not HOME_ASSISTANT_SLEEP_URL:
        warnings.append("HOME_ASSISTANT_SLEEP_URL not set - sleep screen disabled")
    
    # Log results
    if errors:
        logging.error("=" * 50)
        logging.error("CONFIGURATION ERRORS FOUND:")
        for error in errors:
            logging.error(f"  ✗ {error}")
        logging.error("=" * 50)
        return False
    
    if warnings:
        logging.warning("Configuration warnings:")
        for warning in warnings:
            logging.warning(f"  ⚠ {warning}")
    
    logging.info("✓ Configuration validated successfully")
    return True

# ============================================================================
# FONT MANAGEMENT
# ============================================================================
@lru_cache(maxsize=8)
def get_font(size, font_name='AtkinsonHyperlegibleNext-Regular.otf'):
    """Cache fonts to avoid reloading from disk."""
    return ImageFont.truetype(os.path.join(picdir, font_name), size)

@lru_cache(maxsize=4)
def get_font_bold(size):
    """Get bold variant of Atkinson Hyperlegible font."""
    try:
        return ImageFont.truetype(os.path.join(picdir, 'AtkinsonHyperlegibleNext-Bold.otf'), size)
    except:
        logging.warning("Atkinson bold font not found, using regular")
        return get_font(size)

@lru_cache(maxsize=4)
def get_icon_font(size):
    """Get Material Design Icons font for rendering icons."""
    try:
        return ImageFont.truetype(os.path.join(picdir, 'materialdesignicons-webfont.ttf'), size)
    except:
        logging.warning("MDI font not found, using regular font as fallback")
        return get_font(size)

# Material Design Icon Unicode characters (MDI v7.4.47)
class MDI:
    """Material Design Icons Unicode characters for version 7.4.47."""
    BUS = "\U000F010B"
    BUS_MARKER = "\U000F1212"
    BUS_STOP = "\U000F1012"
    BUS_SIDE = "\U000F0710"
    TRAIN = "\U000F04DE"
    TRAIN_VARIANT = "\U000F08C7"
    TRAIN_CAR = "\U000F0BD8"
    SUBWAY = "\U000F06AC"
    SUBWAY_VARIANT = "\U000F0D72"
    ALERT = "\U000F0026"
    ALERT_CIRCLE = "\U000F0027"
    ALERT_CIRCLE_OUTLINE = "\U000F05D6"
    CHECK_CIRCLE = "\U000F05E0"
    CHECK_CIRCLE_OUTLINE = "\U000F05E1"
    CLOCK = "\U000F0954"
    CLOCK_OUTLINE = "\U000F0150"
    UPDATE = "\U000F06A6"
    REFRESH = "\U000F0450"
    WIFI = "\U000F05A9"
    SLEEP = "\U000F098C"
    ACCOUNT_MULTIPLE = "\U000F0004"
    SPEEDOMETER = "\U000F063E"
    HOME = "\U000F02DC"
    HOME_AUTOMATION = "\U000F07D0"
    INFORMATION = "\U000F02FC"
    INFORMATION_OUTLINE = "\U000F02FD"
    # Weather icons
    WEATHER_SUNNY = "\U000F0599"
    WEATHER_CLOUDY = "\U000F0590"
    WEATHER_RAINY = "\U000F0597"
    WEATHER_PARTLY_CLOUDY = "\U000F0595"
    WEATHER_NIGHT = "\U000F0594"
    THERMOMETER = "\U000F0E02"
    WATER_PERCENT = "\U000F058E"
    # Journey/navigation icons
    MAP_MARKER_DISTANCE = "\U000F08F0"
    TIMER = "\U000F13B3"
    NAVIGATION = "\U000F0423"
    # Load/Capacity icons (NEW)
    SEAT_PASSENGER = "\U000F0E2F"           # mdi-seat-passenger (F0E2F)
    HUMAN_MALE = "\U000F0649"               # mdi-human-male (F0649)
    MINUS_CIRCLE_OUTLINE = "\U000F0376"     # mdi-minus-circle-outline (F0376)

BUS_LOAD_MAP_ICON = {
    'SEA': MDI.SEAT_PASSENGER,      # Seats available
    'SDA': MDI.HUMAN_MALE,           # Standing available
    'LSD': MDI.MINUS_CIRCLE_OUTLINE  # Limited standing
}

# ============================================================================
# MQTT CLIENT FOR HOME ASSISTANT
# ============================================================================
class MQTTClient:
    """MQTT client for receiving refresh commands from Home Assistant."""
    
    def __init__(self):
        self.client = None
        self.connected = False
        
        if not MQTT_ENABLED:
            logging.info("MQTT integration disabled")
            return
        
        self.client = mqtt.Client()
        
        # Set callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # Set credentials if provided
        if MQTT_USERNAME and MQTT_PASSWORD:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        
        # Connect in a separate thread to avoid blocking
        threading.Thread(target=self._connect, daemon=True).start()
    
    def _connect(self):
        """Connect to MQTT broker."""
        try:
            logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
        except Exception as e:
            logging.error(f"Failed to connect to MQTT broker: {e}")
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker."""
        if rc == 0:
            self.connected = True
            logging.info("Connected to MQTT broker")
            client.subscribe(MQTT_TOPIC_REFRESH)
            logging.info(f"Subscribed to topic: {MQTT_TOPIC_REFRESH}")
            self.publish_status("online")
        else:
            logging.error(f"Failed to connect to MQTT broker, return code: {rc}")
    
    def on_message(self, client, userdata, msg):
        """Callback when a message is received."""
        logging.info(f"Received MQTT message on {msg.topic}: {msg.payload.decode()}")
        
        if msg.topic == MQTT_TOPIC_REFRESH:
            payload = msg.payload.decode().lower()
            if payload in ['refresh', 'update', 'on', '1', 'true']:
                logging.info("Manual refresh requested via MQTT")
                refresh_requested.set()
                self.publish_status("refreshing")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        if rc != 0:
            logging.warning(f"Unexpected MQTT disconnection. Will auto-reconnect.")
    
    def publish_status(self, status):
        """Publish current status to MQTT."""
        if self.client and self.connected:
            try:
                self.client.publish(MQTT_TOPIC_STATUS, status, retain=True)
            except Exception as e:
                logging.error(f"Failed to publish MQTT status: {e}")
    
    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.publish_status("offline")
            self.client.loop_stop()
            self.client.disconnect()

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
        response = http_session.get(url, headers=headers, timeout=10)
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
        response = http_session.get(url, headers=headers, timeout=15)
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
        
        response = http_session.get(search_url, params=search_params, headers=search_headers, timeout=10)
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
        
        response = http_session.get(route_url, params=route_params, headers=route_headers, timeout=15)
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
        
        response = http_session.get(url, params=params, timeout=15)
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
        response = http_session.get(url, headers=headers, timeout=10)
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
        response = http_session.get(url, headers=headers, timeout=10)
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

def get_weather_icon(condition):
    """Map weather condition to MDI icon."""
    condition_lower = condition.lower() if condition else ""
    
    if 'clear' in condition_lower or 'sunny' in condition_lower:
        return MDI.WEATHER_SUNNY
    elif 'rain' in condition_lower or 'rainy' in condition_lower:
        return MDI.WEATHER_RAINY
    elif 'cloud' in condition_lower:
        if 'partly' in condition_lower or 'partial' in condition_lower:
            return MDI.WEATHER_PARTLY_CLOUDY
        return MDI.WEATHER_CLOUDY
    elif 'night' in condition_lower:
        return MDI.WEATHER_NIGHT
    else:
        return MDI.WEATHER_PARTLY_CLOUDY

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

# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================
class DisplayManager:
    """Manages image buffers for the e-ink display."""
    def __init__(self, epd):
        self.epd = epd
        self.black_image = Image.new('1', (epd.width, epd.height), 255)
        self.red_image = Image.new('1', (epd.width, epd.height), 255)
    
    def clear_images(self):
        """Clear both image buffers and return draw objects."""
        self.black_image.paste(255, (0, 0, self.epd.width, self.epd.height))
        self.red_image.paste(255, (0, 0, self.epd.width, self.epd.height))
        return ImageDraw.Draw(self.black_image), ImageDraw.Draw(self.red_image)
    
    def display(self):
        """Update the e-ink display with current image buffers."""
        self.epd.display(self.epd.getbuffer(self.black_image), 
                        self.epd.getbuffer(self.red_image))

def draw_mdi_icon(draw, x, y, icon_char, size=50, color=0):
    """Draw a Material Design Icon at the specified position."""
    icon_font = get_icon_font(size)
    draw.text((x, y), icon_char, font=icon_font, fill=color)

def draw_timestamp(draw_r, epd_width, x=None, y=10, manual=False):
    """Draw the last updated timestamp at the top right of the screen."""
    now = datetime.now()
    formatted_time = now.strftime("%H:%M")
    formatted_date = now.strftime("%d %b %Y")
    
    timestamp_font = get_font(18)
    small_font = get_font(12)
    
    time_text = f"Updated: {formatted_time}"
    if manual:
        time_text += " ★"
    
    if x is None:
        bbox = timestamp_font.getbbox(time_text)
        text_width = bbox[2] - bbox[0]
        x = epd_width - text_width - 15
    
    draw_r.text((x, y), time_text, font=timestamp_font, fill=0)
    
    bbox = small_font.getbbox(formatted_date)
    date_width = bbox[2] - bbox[0]
    date_x = epd_width - date_width - 15
    draw_r.text((date_x, y + 22), formatted_date, font=small_font, fill=0)

def draw_bus_section(draw, draw_r, bus_info, font, y_start, load_font, journey_times=None):
    """Draw the bus arrival section with journey times and destination header."""
    y = y_start
    bus_number_font = get_font_bold(BUS_NUMBER_FONT_SIZE)
    journey_font = get_font(18)
    dest_header_font = get_font(16)
    
    # Get display name for destination
    dest_display = JOURNEY_DESTINATION_SHORT if JOURNEY_DESTINATION_SHORT else JOURNEY_DESTINATION
    if len(dest_display) > 25:
        dest_display = dest_display[:22] + "..."
    
    # Draw destination header at top if journey time is enabled
    if SHOW_JOURNEY_TIME and journey_times and dest_display:
        header_y = y
        draw_mdi_icon(draw_r, 25, header_y, MDI.MAP_MARKER_DISTANCE, size=20, color=0)
        draw.text((50, header_y + 2), f"Journeys to: {dest_display}", font=dest_header_font, fill=0)
        draw.line((20, header_y + 26, 400, header_y + 26), fill=0, width=1)
        y += 35
    
    for service_no, arrival_times, load_rates in bus_info:
        # Draw bus number box
        box_top = y + 10
        box_height = BUS_BOX_HEIGHT
        box_center_y = box_top + (box_height / 2)
        
        draw.rectangle((20, box_top, 20 + BUS_BOX_WIDTH, box_top + box_height), fill=0)
        
        # Bus number
        bus_bbox = bus_number_font.getbbox(service_no)
        bus_text_height = bus_bbox[3] - bus_bbox[1]
        bus_text_y = box_center_y - (bus_text_height / 2) - 5
        draw.text((50, bus_text_y), service_no, font=bus_number_font, fill=255)
        
        # Arrival times - show "Arr" for 0 minutes
        times_display = []
        for time in arrival_times:
            if time <= 0:
                times_display.append("Arr")
            else:
                times_display.append(str(time))
        
        times_text = " | ".join(times_display)
        times_bbox = font.getbbox(times_text)
        times_text_height = times_bbox[3] - times_bbox[1]
        times_text_y = box_center_y - (times_text_height / 2)
        draw.text((200, times_text_y), times_text, font=font, fill=0)
        
        # Load indicator with icon - UPDATED
        if load_rates:
            load_code = load_rates[0]
            load_text = BUS_LOAD_MAP_TEXT.get(load_code, '?')
            load_size = BUS_LOAD_MAP_SIZE.get(load_code, 0)
            load_icon = BUS_LOAD_MAP_ICON.get(load_code)
            
            # Calculate vertical center for load text
            load_bbox = load_font.getbbox(load_text)
            load_text_height = load_bbox[3] - load_bbox[1]
            load_text_y = box_center_y + (box_height / 4) - (load_text_height / 2) + 8
            
            # Draw load icon in red (before text)
            if load_icon:
                draw_mdi_icon(draw_r, 195, load_text_y - 2, load_icon, size=16, color=0)
                # Draw load text after icon (adjusted position)
                draw_r.text((213, load_text_y), load_text, font=load_font, fill=0)
            else:
                # Fallback if no icon
                draw_r.text((200, load_text_y), load_text, font=load_font, fill=0)
            
            # Draw load bar
            draw.rectangle((150, box_top + 5, 170, box_top + box_height - 5), fill=255)
            draw_r.rectangle((150, box_top + box_height - 5 - load_size // 2, 
                            170, box_top + box_height - 5), fill=0)
        
        # Draw journey time if available
        if journey_times and service_no in journey_times:
            details = journey_times[service_no]
            
            journey_y = box_top + box_height + 8
            
            # Red timer icon
            draw_mdi_icon(draw_r, 25, journey_y, MDI.TIMER, size=18, color=0)
            
            # Black journey text
            journey_text = f"{details['total_time']}min (arrive ~{details['arrival_time']})"
            draw.text((48, journey_y + 2), journey_text, font=journey_font, fill=0)
        
        y += BUS_BOX_Y_SPACING
    
    return y

def draw_weather_section_right(draw, draw_r, weather_info, x_start, epd_width, epd_height):
    """Draw the weather section in right column below train status."""
    if not weather_info:
        return
    
    # Position weather in right column - fixed position from bottom
    weather_y = epd_height - WEATHER_SECTION_HEIGHT
    
    # Draw separator line
    draw_r.line((x_start, weather_y, epd_width - 10, weather_y), fill=0, width=1)
    weather_y += 15
    
    # Weather header
    weather_header_font = get_font_bold(20)
    draw.text((x_start, weather_y), "Weather", font=weather_header_font, fill=0)
    weather_y += 28
    
    # Draw weather icon
    weather_icon = get_weather_icon(weather_info.get('condition'))
    draw_mdi_icon(draw, x_start, weather_y, weather_icon, size=35, color=0)
    
    # Draw temperature
    temp = weather_info.get('temperature')
    if temp:
        draw_r.text((x_start + 45, weather_y + 5), f"{temp}°C", font=get_font(FONT_LARGE), fill=0)
    
    # Draw condition
    condition = weather_info.get('condition', '').title()
    draw.text((x_start, weather_y + 40), condition[:15], font=get_font(FONT_MEDIUM), fill=0)
    
    # Draw humidity if available
    humidity = weather_info.get('humidity')
    if humidity:
        draw_mdi_icon(draw_r, x_start, weather_y + 65, MDI.WATER_PERCENT, size=18, color=0)
        draw_r.text((x_start + 23, weather_y + 65), f"{humidity}%", font=get_font(14), fill=0)

def draw_train_section(draw, draw_r, train_info, train_x, epd_width, epd_height):
    """Draw the train disruption section and return final y position."""
    train_font = get_font(20)
    train_header_font = get_font_bold(28)
    
    draw_mdi_icon(draw, train_x - 5, 8, MDI.SUBWAY, size=40, color=0)
    
    draw_r.text((train_x + 45, 18), "Train Status", font=train_header_font, fill=0)
    draw_r.line((train_x, 55, epd_width - 10, 55), fill=0, width=1)
    
    y_offset = 70
    
    if train_info == "No Disruptions Today!":
        draw_mdi_icon(draw_r, train_x, y_offset, MDI.CHECK_CIRCLE, size=24, color=0)
        
        draw.text((train_x + 30, y_offset + 2), "All trains running", font=train_font, fill=0)
        y_offset += 32
        draw.text((train_x + 30, y_offset), "smoothly today!", font=train_font, fill=0)
        y_offset += 32
        draw.text((train_x + 30, y_offset), "No disruptions", font=train_font, fill=0)
        y_offset += 28
        draw.text((train_x + 30, y_offset), "expected.", font=train_font, fill=0)
        y_offset += 32
    elif train_info:
        for disruption in train_info['disruptions']:
            draw_mdi_icon(draw_r, train_x, y_offset, MDI.ALERT_CIRCLE, size=20, color=0)
            
            draw_r.text((train_x + 25, y_offset), f"Line: {disruption['Line']}", 
                       font=train_font, fill=0)
            y_offset += 32
            
            draw.text((train_x + 25, y_offset), f"Dir: {disruption['Direction']}", 
                     font=train_font, fill=0)
            y_offset += 32
            
            stations = ", ".join(disruption['Stations'])
            wrapped_stations = textwrap.wrap(stations, width=22)
            for line in wrapped_stations[:2]:
                draw.text((train_x + 25, y_offset), line, font=get_font(16), fill=0)
                y_offset += 24
            
            y_offset += 15

            # Stop if getting too long to leave room for weather (which starts
            # at epd_height - WEATHER_SECTION_HEIGHT in the same column)
            if y_offset > epd_height - WEATHER_SECTION_HEIGHT:
                break

        if train_info.get('content') and y_offset < epd_height - WEATHER_SECTION_HEIGHT + 20:
            y_offset += 10
            draw_r.line((train_x, y_offset, epd_width - 10, y_offset), fill=0, width=1)
            y_offset += 15
            
            draw_mdi_icon(draw_r, train_x, y_offset, MDI.ALERT, size=18, color=0)
            draw_r.text((train_x + 22, y_offset), "Alert:", font=get_font(16), fill=0)
            y_offset += 28
            
            wrapped_text = textwrap.wrap(train_info['content'], width=22)
            for line in wrapped_text[:3]:
                draw.text((train_x + 25, y_offset), line, font=get_font(14), fill=0)
                y_offset += 22
    
    return y_offset  # Return final position

def display_combined_view(display_mgr, font, bus_info, train_info, weather_info, journey_times=None, manual_refresh=False, mqtt_client=None):
    """Display bus arrivals on left, train disruptions and weather on right."""
    logging.debug("Displaying combined bus, train, and weather info...")
    
    draw, draw_r = display_mgr.clear_images()
    epd = display_mgr.epd
    
    column_offset = epd.width // 2
    load_font = get_font(LOAD_FONT_SIZE)
    bus_header_font = get_font_bold(28)
    
    mqtt_connected = mqtt_client.connected if mqtt_client else False
    
    draw_mdi_icon(draw, 15, 5, MDI.BUS_MARKER, size=50, color=0)
    draw_timestamp(draw_r, epd.width, manual=manual_refresh)
    
    if mqtt_connected:
        draw_mdi_icon(draw_r, epd.width - 70, epd.height - 70, MDI.HOME_AUTOMATION, size=50, color=0)
    
    draw_r.line((column_offset, 60, column_offset, epd.height - 10), 
                fill=0, width=DIVIDER_WIDTH)
    
    # ========== LEFT COLUMN: BUS ARRIVALS ONLY ==========
    draw_r.text((80, 18), HEADER_A, font=bus_header_font, fill=0)
    draw_r.line((10, 55, column_offset - 10, 55), fill=0, width=1)
    
    final_bus_y = draw_bus_section(draw, draw_r, bus_info, font, BUS_BOX_Y_OFFSET, load_font, journey_times)
    
    # ========== RIGHT COLUMN: TRAIN STATUS AND WEATHER ==========
    train_x = column_offset + 20
    
    # Draw train status
    final_train_y = draw_train_section(draw, draw_r, train_info, train_x, epd.width, epd.height)
    
    # Draw weather below train status in right column
    draw_weather_section_right(draw, draw_r, weather_info, train_x, epd.width, epd.height)
    
    system_health.record_display_update(manual=manual_refresh)
    
    display_mgr.display()

def display_debug_screen(display_mgr, boot_time):
    """Display debug information with all environment variables."""
    draw, draw_r = display_mgr.clear_images()
    epd = display_mgr.epd
    
    draw_mdi_icon(draw, 15, 5, MDI.BUS_MARKER, size=40, color=0)
    draw_r.text((70, 15), "DEBUG MODE", font=get_font_bold(28), fill=0)
    draw_r.line((10, 50, epd.width - 10, 50), fill=0, width=2)
    
    debug_font = get_font(11)
    y_pos = 60
    line_spacing = 17
    column_split = epd.width // 2
    
    left_vars = [
        f"Boot: {boot_time}",
        f"Log: {LOG_LEVEL}",
        "",
        f"Origin: {BUS_STOP_CODE_A}",
        f"Name: {HEADER_A[:25]}",
        "",
        f"Journey: {'On' if SHOW_JOURNEY_TIME else 'Off'}",
        f"Dest: {JOURNEY_DESTINATION[:22]}" if JOURNEY_DESTINATION else "Dest: Not Set",
        f"API: {ROUTING_API_PROVIDER.upper()}",
        f"Track: {','.join(BUS_SERVICES_TO_TRACK[:3])}" if BUS_SERVICES_TO_TRACK else "Track: None",
        "",
        f"Wake: {WAKE_HOUR}:00",
        f"Sleep: {SLEEP_HOUR}:00",
    ]
    
    right_vars = [
        f"Wake Int: {WAKE_INTERVAL}s",
        f"Sleep Int: {SLEEP_INTERVAL}s",
        "",
        f"MQTT: {'On' if MQTT_ENABLED else 'Off'}",
        f"Broker: {MQTT_BROKER}" if MQTT_ENABLED else "",
        "",
        f"Cache: {CACHE_DURATION}s",
        f"Weather: {WEATHER_CACHE_DURATION}s",
        f"Journey: {JOURNEY_TIME_CACHE_DURATION}s",
        "",
        f"APIs configured",
        f"Routing ready",
    ]
    
    y = y_pos
    for var in left_vars:
        if var:
            draw.text((15, y), var, font=debug_font, fill=0)
        y += line_spacing
    
    y = y_pos
    for var in right_vars:
        if var:
            draw.text((column_split + 10, y), var, font=debug_font, fill=0)
        y += line_spacing
    
    draw_r.text((15, epd.height - 25), 
               "Displaying for 5 seconds...", 
               font=get_font(14), fill=0)
    
    display_mgr.display()
    logging.info("DEBUG MODE: Displaying environment variables for 5 seconds")
    time.sleep(5)

def display_sleep_screen(display_mgr, image_url):
    """Fetch and display the sleep screen from Home Assistant."""
    url_param = (f"{SLEEP_SCREEN_DASHBOARD}/0?viewport="
                f"{display_mgr.epd.width}x{display_mgr.epd.height}"
                f"&eink={SLEEP_SCREEN_EINK_MODE}"
                f"&zoom={SLEEP_SCREEN_ZOOM}"
                f"&wait={SLEEP_SCREEN_WAIT}"
                f"&theme={SLEEP_SCREEN_THEME}")
    
    full_url = image_url + url_param
    logging.info(f"Fetching sleep screen from: {full_url}")
    
    try:
        response = http_session.get(full_url, timeout=50)
        response.raise_for_status()
        
        image = Image.open(io.BytesIO(response.content))
        bw_image = image.convert('L')
        red_image = Image.new('1', (display_mgr.epd.width, display_mgr.epd.height), 255)
        
        logging.info("Displaying sleep screen...")
        display_mgr.epd.display(display_mgr.epd.getbuffer(bw_image), 
                               display_mgr.epd.getbuffer(red_image))
        return True
        
    except requests.RequestException as e:
        logging.error(f"Failed to fetch sleep screen: {e}")
        return False

# ============================================================================
# CLEANUP AND SIGNAL HANDLING
# ============================================================================
def cleanup():
    """Cleanup function to run on exit."""
    try:
        logging.info("Starting cleanup...")
        
        if 'mqtt_client' in globals() and mqtt_client:
            mqtt_client.disconnect()
            logging.info("MQTT disconnected")
        
        if http_session:
            http_session.close()
            logging.info("HTTP session closed")
        
        system_health.log_stats()
        
        logging.info("Cleanup completed successfully")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

atexit.register(cleanup)

def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============================================================================
# MAIN LOOP
# ============================================================================
def is_in_wake_window(current_hour):
    """Determine if current time is within the wake window."""
    if WAKE_HOUR > SLEEP_HOUR:
        return (current_hour >= WAKE_HOUR) or (current_hour < SLEEP_HOUR)
    else:
        return (current_hour >= WAKE_HOUR) and (current_hour < SLEEP_HOUR)

def main():
    """Main application loop."""
    global mqtt_client
    mqtt_client = None
    
    try:
        logging.info("=" * 60)
        logging.info("Bus Arrival Display with API-based Journey Times")
        logging.info("=" * 60)
        
        if not validate_configuration():
            logging.error("Configuration validation failed. Please check your .env file.")
            return 1
        
        # Log journey configuration
        if SHOW_JOURNEY_TIME:
            logging.info(f"Journey Time Tracking ENABLED")
            logging.info(f"  Routing API: {ROUTING_API_PROVIDER.upper()}")
            logging.info(f"  Origin: Bus stop {BUS_STOP_CODE_A}")
            logging.info(f"  Destination: {JOURNEY_DESTINATION}")
            logging.info(f"  Tracking services: {', '.join(BUS_SERVICES_TO_TRACK)}")
        else:
            logging.info("Journey time tracking DISABLED")
        
        mqtt_client = MQTTClient()
        
        epd = epd7in5b_V2.EPD()
        epd.init()
        epd.Clear()
        
        display_mgr = DisplayManager(epd)
        
        boot_time = datetime.now().strftime("%H:%M on %d %b %Y")
        
        if DEBUG_SKIP_TIME_CHECK:
            display_debug_screen(display_mgr, boot_time)
        else:
            draw, draw_r = display_mgr.clear_images()
            boot_font = get_font_bold(FONT_LARGE)
            
            draw_mdi_icon(draw, 15, 5, MDI.BUS_MARKER, size=50, color=0)
            
            draw.text((85, 18), "System Starting...", font=boot_font, fill=0)
            draw_r.text((epd.width // 2 - 100, epd.height // 2), 
                       f"Booted: {boot_time}", font=get_font(18), fill=0)
            
            display_mgr.display()
        
        default_font = get_font(BUS_NUMBER_FONT_SIZE)
        is_sleeping = False
        stats_counter = 0
        
        while True:
            watchdog.feed()
            
            if not watchdog.check():
                logging.critical("Watchdog detected stuck loop - restarting...")
                return 1
            
            current_hour = datetime.now().hour
            manual_refresh = False
            
            if refresh_requested.is_set():
                logging.info("Processing manual refresh request")
                manual_refresh = True
                refresh_requested.clear()
                cache.clear()
                
                if is_sleeping:
                    logging.info("Waking display for manual refresh")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False
            
            if not DEBUG_SKIP_TIME_CHECK:
                if not is_in_wake_window(current_hour) and not manual_refresh:
                    if not is_sleeping:
                        logging.info(f"Outside wake window. Entering sleep mode until {WAKE_HOUR}:00")
                        
                        if mqtt_client:
                            mqtt_client.publish_status("sleeping")
                        
                        if HOME_ASSISTANT_SLEEP_URL and display_sleep_screen(display_mgr, HOME_ASSISTANT_SLEEP_URL):
                            logging.debug("Sleep screen displayed successfully")
                            epd.sleep()
                            is_sleeping = True
                        else:
                            logging.warning("Could not display sleep screen, will retry")
                    
                    time.sleep(SLEEP_INTERVAL)
                    continue
                
                if is_sleeping:
                    logging.info(f"Waking up display")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False
                    
                    if mqtt_client:
                        mqtt_client.publish_status("awake")
            else:
                if is_sleeping:
                    logging.info("DEBUG mode: Waking display")
                    epd.init()
                    epd.Clear()
                    is_sleeping = False
            
            # Fetch all data including API-based journey times
            bus_info, train_info, weather_info, journey_times = fetch_data_parallel(force_refresh=manual_refresh)
            
            display_combined_view(display_mgr, default_font, bus_info, train_info, weather_info,
                                journey_times=journey_times, manual_refresh=manual_refresh, mqtt_client=mqtt_client)
            
            if mqtt_client:
                mqtt_client.publish_status("idle")
            
            stats_counter += 1
            if stats_counter >= 10:
                system_health.log_stats()
                stats_counter = 0
            
            time.sleep(WAKE_INTERVAL)
    
    except IOError as e:
        logging.error(f"IO Error: {e}")
        logging.debug(traceback.format_exc())
        return 1
    
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
        return 0
    
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        logging.debug(traceback.format_exc())
        return 1
    
    finally:
        if mqtt_client:
            mqtt_client.disconnect()
        epd7in5b_V2.epdconfig.module_exit(cleanup=True)
        logging.info("Application terminated")

if __name__ == "__main__":
    sys.exit(main())

# V13 END
### ---------