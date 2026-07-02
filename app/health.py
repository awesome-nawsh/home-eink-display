"""Loop-health monitoring: systemd watchdog pings and running system/API-call
statistics.

The previous in-process Watchdog class was structurally inert — it fed and
checked itself from the same thread, so a genuinely hung loop could never
reach the check. Real hang protection now comes from systemd: the unit file
sets Type=notify + WatchdogSec, main.py pings sd_notify('WATCHDOG=1') every
loop tick, and systemd itself kills and restarts the process if the pings
stop.
"""
import logging
import os
import socket
from datetime import datetime, timedelta

from config import boot_timestamp

# Try to import psutil for system monitoring (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available - system monitoring disabled")


def sd_notify(message):
    """Minimal systemd notification (no sdnotify dependency): writes `message`
    (e.g. 'READY=1', 'WATCHDOG=1') to the datagram socket systemd provides
    via $NOTIFY_SOCKET when the unit is Type=notify. Silently a no-op when
    not running under systemd (dev machine, plain `python3 main.py`), so
    callers never need to care."""
    sock_path = os.environ.get('NOTIFY_SOCKET')
    if not sock_path:
        return
    if sock_path.startswith('@'):  # abstract-namespace socket
        sock_path = '\0' + sock_path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(sock_path)
            s.sendall(message.encode())
    except OSError as e:
        logging.debug(f"sd_notify({message!r}) failed: {e}")


class SystemHealth:
    """Track and report system health metrics."""
    def __init__(self):
        self.metrics = {
            'api_calls': {'bus': 0, 'train': 0, 'weather': 0, 'routing': 0, 'day_type': 0},
            'api_errors': {'bus': 0, 'train': 0, 'weather': 0, 'routing': 0, 'day_type': 0},
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
system_health = SystemHealth()
