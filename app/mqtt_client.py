"""MQTT client for Home Assistant integration: subscribes for manual-refresh
and config_reload commands, and publishes display lifecycle status.

Uses the paho-mqtt 2.x callback API (CallbackAPIVersion.VERSION2) —
requirements.txt pins paho-mqtt>=2.0 to match.
"""
import logging
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

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        # Set callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        # Set credentials if provided (some brokers allow a username with an
        # empty password, so only the username is required here)
        if MQTT_USERNAME:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD or None)

        # connect_async + loop_start: paho's network thread owns the initial
        # connection AND keeps retrying if the broker is down at boot — a
        # plain connect() here would fail once and never self-heal, leaving
        # MQTT dead for the life of the process after a reboot during a
        # broker/HA outage.
        logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        self.client.connect_async(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.connected = True
            logging.info("Connected to MQTT broker")
            client.subscribe(MQTT_TOPIC_REFRESH)
            logging.info(f"Subscribed to topic: {MQTT_TOPIC_REFRESH}")
            client.subscribe(MQTT_TOPIC_CONFIG_RELOAD)
            logging.info(f"Subscribed to topic: {MQTT_TOPIC_CONFIG_RELOAD}")
            self.publish_status("online")
        else:
            logging.error(f"Failed to connect to MQTT broker, reason: {reason_code}")

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

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        if reason_code != 0:
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
