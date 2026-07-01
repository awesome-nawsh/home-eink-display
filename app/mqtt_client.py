"""MQTT client for Home Assistant integration: subscribes for manual-refresh
commands and publishes display lifecycle status.
"""
import logging
import threading
import paho.mqtt.client as mqtt

from config import (
    MQTT_ENABLED, MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD,
    MQTT_TOPIC_REFRESH, MQTT_TOPIC_STATUS, MQTT_TOPIC_CONFIG_RELOAD,
    refresh_requested, config_reload_requested,
)


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
            client.subscribe(MQTT_TOPIC_CONFIG_RELOAD)
            logging.info(f"Subscribed to topic: {MQTT_TOPIC_CONFIG_RELOAD}")
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

        elif msg.topic == MQTT_TOPIC_CONFIG_RELOAD:
            logging.info("Config reload requested via MQTT")
            config_reload_requested.set()

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
