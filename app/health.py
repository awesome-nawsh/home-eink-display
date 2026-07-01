"""Loop-health monitoring: watchdog for stuck-process detection and running
system/API-call statistics.
"""
import logging
from datetime import datetime, timedelta

from config import WATCHDOG_TIMEOUT, boot_timestamp

# Try to import psutil for system monitoring (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available - system monitoring disabled")


class Watchdog:
    """Monitors main loop health and detects stuck processes."""
    def __init__(self, timeout=WATCHDOG_TIMEOUT):
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
watchdog = Watchdog(timeout=WATCHDOG_TIMEOUT)
system_health = SystemHealth()
