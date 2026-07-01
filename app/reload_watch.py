"""Pure file-change detection used by main.py's mtime-poll reload backstop
(the MQTT config_reload topic is the fast path; this is what catches changes
made by editing files directly, e.g. over SSH, without going through the
web UI). No hardware/Flask dependency.
"""
import os


def get_mtime(path):
    """Returns the file's mtime, or None if it doesn't exist."""
    return os.path.getmtime(path) if os.path.exists(path) else None


def has_changed(path, last_mtime):
    """Returns (changed: bool, current_mtime) comparing the file's current
    mtime against `last_mtime`. A file that didn't exist before and still
    doesn't exist is "unchanged" (None == None)."""
    current = get_mtime(path)
    return current != last_mtime, current
