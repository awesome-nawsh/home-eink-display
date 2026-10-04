"""main.cleanup() runs once per shutdown even though it's reached up to
three ways (signal handler, main()'s finally, atexit). main.py imports the
waveshare driver and pigpio, so those are stubbed here."""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import tests  # noqa: F401 (adds app/ to sys.path)


def import_main():
    waveshare = types.ModuleType('waveshare_epd')
    waveshare.epd7in5b_V2 = MagicMock()
    stubs = {'waveshare_epd': waveshare, 'waveshare_epd.epd7in5b_V2': waveshare.epd7in5b_V2,
             'pigpio': types.ModuleType('pigpio')}
    with patch.dict(sys.modules, stubs), \
         patch('signal.signal'), patch('atexit.register'):
        sys.modules.pop('main', None)
        import main
    return main


class TestCleanupRunsOnce(unittest.TestCase):
    def test_second_call_is_a_no_op(self):
        main = import_main()
        mqtt = MagicMock()
        with patch.object(main, 'mqtt_client', mqtt, create=True), \
             patch.object(main, 'http_session') as session, \
             patch.object(main.system_health, 'log_stats') as log_stats:
            main.cleanup()
            main.cleanup()
            main.cleanup()
        mqtt.disconnect.assert_called_once()
        session.close.assert_called_once()
        log_stats.assert_called_once()


if __name__ == "__main__":
    unittest.main()
