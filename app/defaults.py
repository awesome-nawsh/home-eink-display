"""Default values shared by config.py (the display process) and web_config.py
(the web panel). Two separate processes read the same .env, so these used to
be written out twice with a "must match config.py" comment — now there's one
copy.

Pure constants, no side effects: web_config.py deliberately doesn't import
config.py, whose import configures logging, creates the secrets key and
validates FORCE_SCREEN.
"""
import os

APP_DIR = os.path.dirname(os.path.realpath(__file__))

ENV_FILE_PATH = os.path.join(APP_DIR, '.env')
SCHEDULE_CONFIG_PATH = os.path.join(APP_DIR, 'schedule_config.json')
SECRETS_KEY_PATH = os.path.join(APP_DIR, '.encryption_key')
# Rewritten every loop tick, so kept off the SD card (see config.py)
STATUS_FILE_PATH = '/tmp/bus_display_status.json'

# Legacy wake/sleep hours — only the fallback-schedule input (scheduler.py)
WAKE_HOUR = 7
SLEEP_HOUR = 22

MQTT_BROKER = 'localhost'
MQTT_PORT = 1883
MQTT_TOPIC_REFRESH = 'eink/display/refresh'
MQTT_TOPIC_STATUS = 'eink/display/status'
MQTT_TOPIC_CONFIG_RELOAD = 'eink/display/config_reload'
