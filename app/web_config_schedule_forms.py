"""Pure form-data <-> schedule dict conversion, and the atomic JSON writer
for schedule_config.json. Validation is always delegated to scheduler.py
(validate_schedule/detect_overlaps) — never reimplemented here.
"""
import json
import os
import tempfile

from scheduler import SCREEN_NAMES, DISABLEABLE_SCREENS


def schedule_from_form(form):
    """Builds a candidate schedule dict from submitted form fields named
    '<screen>_start'/'<screen>_end' for each of scheduler.SCREEN_NAMES, plus
    '<screen>_enabled' (a checkbox, so its absence means unchecked) for
    screens in scheduler.DISABLEABLE_SCREENS. Screens outside that set never
    get an 'enabled' key — scheduler.py treats a missing key as always-on."""
    screens = {}
    for name in SCREEN_NAMES:
        window = {"start": form.get(f"{name}_start", ""), "end": form.get(f"{name}_end", "")}
        if name in DISABLEABLE_SCREENS:
            window["enabled"] = form.get(f"{name}_enabled") == "true"
        screens[name] = window
    return {"version": 1, "screens": screens}


def atomic_write_json(path, data):
    """Write JSON to `path` atomically: write to a temp file in the same
    directory, then os.replace() over the target. Prevents a crash/power-loss
    mid-write from corrupting schedule_config.json."""
    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.schedule_config_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
