"""CONFIG_SCHEMA: drives both the .env-editing form and how submitted values
are read back (see web_config_env.py). Pure data, no logic — kept in its own
module so it's easy to review/diff independently of behavior changes.

Field dict keys: type (text|password|number|select|checkbox), label,
required, default (optional), options (for select), min/max (for number),
placeholder (optional), note (optional — extra helper text distinct from
placeholder, e.g. deprecation/legacy-fallback explanations).
"""
from scheduler import SCREEN_NAMES

CONFIG_SCHEMA = {
    'Core Settings': {
        'API_KEY': {'type': 'password', 'label': 'LTA DataMall API Key', 'required': True},
        'BUS_STOP_CODE_A': {'type': 'text', 'label': 'Bus Stop Code', 'required': True},
        'A_HEADER': {'type': 'text', 'label': 'Bus Stop Display Name', 'required': False},
        'API_BUS_URL': {'type': 'text', 'label': 'Bus Arrival API URL', 'required': False, 'default': 'https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival'},
        'API_TRAIN_URL': {'type': 'text', 'label': 'Train Service Alerts API URL', 'required': False, 'default': 'https://datamall2.mytransport.sg/ltaodataservice/TrainServiceAlerts'},
        'API_BUS_STOP_INFO_URL': {'type': 'text', 'label': 'Bus Stop Info API URL', 'required': False, 'default': 'https://datamall2.mytransport.sg/ltaodataservice/BusStops'},
        'LOG_LEVEL': {'type': 'select', 'label': 'Log Level', 'options': ['DEBUG', 'INFO', 'WARNING', 'ERROR'], 'required': False},
    },
    'Journey Time Settings': {
        'SHOW_JOURNEY_TIME': {'type': 'checkbox', 'label': 'Enable Journey Time Tracking', 'required': False},
        'BUS_SERVICES_TO_TRACK': {'type': 'text', 'label': 'Bus Services to Track (comma-separated)', 'required': False, 'placeholder': '67,969,75'},
        'JOURNEY_DESTINATION': {'type': 'text', 'label': 'Journey Destination', 'required': False, 'placeholder': 'School Name, Singapore'},
        'JOURNEY_DESTINATION_SHORT': {'type': 'text', 'label': 'Short Display Name (optional)', 'required': False, 'placeholder': 'School'},
        'ROUTING_API_PROVIDER': {'type': 'select', 'label': 'Routing API Provider', 'options': ['onemap', 'google'], 'required': False},
        'GOOGLE_MAPS_API_KEY': {'type': 'password', 'label': 'Google Maps API Key', 'required': False},
        'ONEMAP_API_KEY': {'type': 'password', 'label': 'OneMap API Key (optional)', 'required': False},
        'JOURNEY_TIME_CACHE_DURATION': {'type': 'number', 'label': 'Journey Cache Duration (seconds)', 'required': False, 'default': '1800'},
    },
    'Schedule Settings (Legacy Fallback)': {
        'WAKE_HOUR': {'type': 'number', 'label': 'Wake Hour (24hr format)', 'required': False, 'default': '7', 'min': '0', 'max': '23',
                      'note': 'Legacy fallback — only used if schedule_config.json is missing or invalid. Edit the schedule directly on the Schedule page.'},
        'SLEEP_HOUR': {'type': 'number', 'label': 'Sleep Hour (24hr format)', 'required': False, 'default': '22', 'min': '0', 'max': '23',
                       'note': 'Legacy fallback — see Schedule page.'},
        'WAKE_INTERVAL': {'type': 'number', 'label': 'Wake Update Interval (seconds)', 'required': False, 'default': '30'},
        'SLEEP_INTERVAL': {'type': 'number', 'label': 'Sleep Update Interval (seconds)', 'required': False, 'default': '300'},
        'DEBUG_SKIP_TIME_CHECK': {'type': 'checkbox', 'label': 'Debug Mode (Always Awake)', 'required': False},
    },
    'Day-Type & Scheduler': {
        'HOME_ASSISTANT_SCHOOL_DAY_ENTITY': {'type': 'text', 'label': 'School Day Sensor Entity', 'required': False, 'default': 'binary_sensor.school_day'},
        'HOME_ASSISTANT_WORKDAY_ENTITY': {'type': 'text', 'label': 'Workday Sensor Entity', 'required': False, 'default': 'binary_sensor.workday_sensor'},
        'DAY_TYPE_FALLBACK': {'type': 'select', 'label': 'Day-Type Fallback', 'options': ['school_day', 'work_day', 'off_day'], 'required': False},
        'BOOT_CHECK_TIMEOUT': {'type': 'number', 'label': 'Boot Connectivity Check Timeout (seconds)', 'required': False, 'default': '3'},
        'INTERNET_CHECK_URL': {'type': 'text', 'label': 'Internet Reachability Check URL', 'required': False, 'default': 'https://www.google.com/generate_204'},
        'FORCE_SCREEN': {
            'type': 'select', 'label': 'Force Screen (testing only — leave blank for normal operation)',
            'options': [''] + list(SCREEN_NAMES), 'required': False, 'dynamic': True,
        },
    },
    'Home Assistant': {
        'HOME_ASSISTANT_API_URL': {'type': 'text', 'label': 'Home Assistant API URL', 'required': False, 'placeholder': 'http://homeassistant.local:8123'},
        'HOME_ASSISTANT_TOKEN': {'type': 'password', 'label': 'Home Assistant Long-Lived Token', 'required': False},
        'HOME_ASSISTANT_WEATHER_ENTITY': {'type': 'text', 'label': 'Weather Entity ID', 'required': False, 'default': 'weather.home'},
        'HOME_ASSISTANT_DASHBOARD_URL': {'type': 'text', 'label': 'Dashboard/Screenshot URL (ha_screen)', 'required': False,
                                          'note': 'Renamed from HOME_ASSISTANT_SLEEP_URL, which is still read as a fallback if this is unset, but no longer written by this UI.'},
        'WEATHER_CACHE_DURATION': {'type': 'number', 'label': 'Weather Cache Duration (seconds)', 'required': False, 'default': '1800'},
    },
    'ha_screen (Dashboard Screenshot)': {
        # Renamed from the legacy SLEEP_SCREEN_* prefix — config.py still
        # reads the old names as fallbacks, but this UI writes the new ones.
        'HA_SCREEN_DASHBOARD': {'type': 'text', 'label': 'Dashboard to Screenshot', 'required': False, 'placeholder': 'http://homeassistant.local:8123/lovelace/eink'},
        'HA_SCREEN_EINK_MODE': {'type': 'select', 'label': 'Puppeteer E-ink Mode', 'options': ['1', '2'], 'required': False,
                                 'note': '1 = black/white, 2 = black/white/red'},
        'HA_SCREEN_ZOOM': {'type': 'text', 'label': 'Zoom Level', 'required': False, 'default': '1'},
        'HA_SCREEN_FORMAT': {'type': 'text', 'label': 'Output Format (optional)', 'required': False, 'placeholder': 'png'},
        'HA_SCREEN_WAIT': {'type': 'number', 'label': 'Wait Before Screenshot (ms)', 'required': False, 'default': '5000'},
        'HA_SCREEN_THEME': {'type': 'text', 'label': 'HA Theme', 'required': False, 'default': 'Graphite E-ink Light'},
    },
    'MQTT Settings': {
        'MQTT_ENABLED': {'type': 'checkbox', 'label': 'Enable MQTT', 'required': False},
        'MQTT_BROKER': {'type': 'text', 'label': 'MQTT Broker Address', 'required': False, 'default': 'localhost'},
        'MQTT_PORT': {'type': 'number', 'label': 'MQTT Port', 'required': False, 'default': '1883'},
        'MQTT_USERNAME': {'type': 'text', 'label': 'MQTT Username', 'required': False},
        'MQTT_PASSWORD': {'type': 'password', 'label': 'MQTT Password', 'required': False},
        'MQTT_TOPIC_REFRESH': {'type': 'text', 'label': 'Refresh Topic', 'required': False, 'default': 'eink/display/refresh'},
        'MQTT_TOPIC_STATUS': {'type': 'text', 'label': 'Status Topic', 'required': False, 'default': 'eink/display/status'},
    },
}
