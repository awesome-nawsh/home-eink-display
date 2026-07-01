"""Pure .env read/build-updates/atomic-write logic — no Flask, testable with
plain dicts and tempfiles. web_config.py wires this to CONFIG_SCHEMA and the
submitted form data.
"""
import os
import tempfile

from dotenv import dotenv_values


def read_env_file(path):
    """Returns a dict of the current .env contents (empty dict if the file
    doesn't exist yet). Uses python-dotenv's dotenv_values() for correct
    parsing (quoting/escaping) rather than a naive manual split."""
    if not os.path.exists(path):
        return {}
    return dict(dotenv_values(path))


def build_env_updates(form, schema, encrypt_fn):
    """Returns (to_set: dict, to_unset: list[str]) built from submitted form
    data and CONFIG_SCHEMA.

    - Checkbox fields always resolve to 'true'/'false' (a checkbox always has
      a definite submitted state — present or absent — never "unchanged").
    - Blank password fields are omitted entirely: password inputs never echo
      their current value back into the form, so blank means "didn't type a
      new one," not "clear it." `encrypt_fn` is applied to non-blank
      password values before they're set.
    - Blank non-password optional fields are unset (removed from .env),
      matching the pre-Phase-3 behavior for those fields.
    """
    to_set = {}
    to_unset = []
    for fields in schema.values():
        for field_name, field_config in fields.items():
            if field_config['type'] == 'checkbox':
                to_set[field_name] = 'true' if form.get(field_name) == 'true' else 'false'
                continue

            value = (form.get(field_name) or '').strip()
            if field_config['type'] == 'password':
                if value:
                    to_set[field_name] = encrypt_fn(value)
                continue

            if value:
                to_set[field_name] = value
            else:
                to_unset.append(field_name)

    return to_set, to_unset


def atomic_write_env_file(path, to_set, to_unset):
    """Atomically rewrites `path`, applying `to_set` (dict) and `to_unset`
    (list of keys to remove) while preserving existing lines/comments/order
    for everything else. Writes to a temp file in the same directory, then
    os.replace()s over the target — a crash mid-write can't leave a
    partially-rewritten .env behind."""
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.readlines()

    remaining_to_set = dict(to_set)
    unset_keys = set(to_unset)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split('=', 1)[0].strip()
        if key in unset_keys:
            continue
        if key in remaining_to_set:
            new_lines.append(f"{key}={remaining_to_set.pop(key)}\n")
        else:
            new_lines.append(line)

    for key, value in remaining_to_set.items():
        new_lines.append(f"{key}={value}\n")

    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.env_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.writelines(new_lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
