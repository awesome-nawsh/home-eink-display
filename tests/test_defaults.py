"""config.py (display process) and web_config.py (web panel) must resolve
the shared paths and MQTT defaults identically — both now read them from
defaults.py instead of each keeping its own copy."""
import os
import unittest

# web_config reads its auth settings once at import; test_web_config_auth
# sets the test values first, so import it through there whichever test
# module happens to load first.
from tests.test_web_config_auth import web_config
import config


class TestSharedDefaults(unittest.TestCase):
    def test_paths_agree(self):
        self.assertEqual(config.ENV_FILE_PATH, web_config.ENV_FILE)
        for name in ('SCHEDULE_CONFIG_PATH', 'SECRETS_KEY_PATH', 'STATUS_FILE_PATH',
                     'WAKE_HOUR', 'SLEEP_HOUR'):
            with self.subTest(name=name):
                self.assertEqual(getattr(config, name), getattr(web_config, name))

    def test_web_publish_defaults_match_display_process(self):
        from unittest.mock import patch
        with patch.object(web_config, 'read_env_file', return_value={}), \
             patch.object(web_config.mqtt_publish, 'single') as single:
            web_config._mqtt_publish('MQTT_TOPIC_REFRESH', web_config.defaults.MQTT_TOPIC_REFRESH, 'x')
        _, kwargs = single.call_args
        if not os.getenv('MQTT_BROKER'):
            self.assertEqual(kwargs['hostname'], config.MQTT_BROKER)
        if not os.getenv('MQTT_PORT'):
            self.assertEqual(kwargs['port'], config.MQTT_PORT)


if __name__ == "__main__":
    unittest.main()
