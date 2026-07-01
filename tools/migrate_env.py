#!/usr/bin/env python3
"""Migrate an existing app/.env file to the Phase 3 format:

- Encrypts password-type field values (API_KEY, GOOGLE_MAPS_API_KEY,
  ONEMAP_API_KEY, HOME_ASSISTANT_TOKEN, MQTT_PASSWORD) that are still
  plaintext, using app/secrets_vault.py (creates app/.encryption_key if it
  doesn't exist yet). Already-encrypted values (enc: prefix) are left alone.
- Copies HOME_ASSISTANT_SLEEP_URL's value to the new HOME_ASSISTANT_DASHBOARD_URL
  key if the new key isn't set yet (the old key is left in place — config.py
  still reads it as a fallback).
- Generates WEB_CONFIG_SECRET_KEY if it's unset or a known placeholder value
  (web_config.py refuses to start with either).
- Generates WEB_CONFIG_PASSWORD_HASH if unset, prompting for a new admin
  password (or reading it from the WEB_CONFIG_NEW_PASSWORD env var, to avoid
  it ever appearing in shell history).
- Copies app/schedule_config.json.example to app/schedule_config.json if the
  real file doesn't exist yet.

A timestamped backup of .env is written before any changes. No secret
VALUES are ever printed to the terminal — only which keys were changed.

Usage:
    python3 tools/migrate_env.py [--env-path PATH] [--yes]

Requires: the same dependencies as app/web_config.py (see requirements.txt).
"""
import argparse
import getpass
import os
import secrets
import shutil
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, 'app')
sys.path.insert(0, APP_DIR)

from werkzeug.security import generate_password_hash  # noqa: E402

from secrets_vault import get_or_create_key, encrypt_value, is_encrypted  # noqa: E402
from web_config_schema import CONFIG_SCHEMA  # noqa: E402
from web_config_env import read_env_file, atomic_write_env_file  # noqa: E402

# Must match web_config.py's own set — a value here is treated the same as
# "unset" and gets a fresh key generated.
KNOWN_BAD_SECRET_KEYS = {'', 'BusAuntieSK', 'change_this_to_a_random_string'}


def plan_updates(config, key):
    """Pure-ish: given the current .env dict and the encryption key, returns
    (to_set: dict, summary: list[str]) — summary describes what changed
    without ever including a secret value."""
    to_set = {}
    summary = []

    for fields in CONFIG_SCHEMA.values():
        for field_name, field_config in fields.items():
            if field_config['type'] != 'password':
                continue
            value = config.get(field_name)
            if not value or is_encrypted(value):
                continue
            to_set[field_name] = encrypt_value(value, key)
            summary.append(f"Encrypted {field_name}")

    if not config.get('HOME_ASSISTANT_DASHBOARD_URL') and config.get('HOME_ASSISTANT_SLEEP_URL'):
        to_set['HOME_ASSISTANT_DASHBOARD_URL'] = config['HOME_ASSISTANT_SLEEP_URL']
        summary.append("Set HOME_ASSISTANT_DASHBOARD_URL from HOME_ASSISTANT_SLEEP_URL "
                        "(the old key is left in place as a fallback)")

    if config.get('WEB_CONFIG_SECRET_KEY') in KNOWN_BAD_SECRET_KEYS:
        to_set['WEB_CONFIG_SECRET_KEY'] = secrets.token_hex(32)
        summary.append("Generated a new WEB_CONFIG_SECRET_KEY")

    return to_set, summary


def prompt_for_new_password_hash():
    password = os.getenv('WEB_CONFIG_NEW_PASSWORD')
    if password:
        print("Using WEB_CONFIG_NEW_PASSWORD from the environment for the new admin password.")
    else:
        password = getpass.getpass("Set the web config admin password (input hidden): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords didn't match — skipping WEB_CONFIG_PASSWORD_HASH generation.", file=sys.stderr)
            return None
    if not password:
        print("Empty password — skipping WEB_CONFIG_PASSWORD_HASH generation.", file=sys.stderr)
        return None
    return generate_password_hash(password)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env-path', default=os.path.join(APP_DIR, '.env'),
                         help='Path to the .env file to migrate (default: app/.env)')
    parser.add_argument('--key-path', default=os.path.join(APP_DIR, '.encryption_key'),
                         help='Path to the secrets encryption key file (default: app/.encryption_key)')
    parser.add_argument('--yes', action='store_true', help='Apply changes without an interactive confirmation prompt')
    parser.add_argument('--skip-password-prompt', action='store_true',
                         help="Don't prompt for a new admin password even if WEB_CONFIG_PASSWORD_HASH is unset")
    args = parser.parse_args()

    if not os.path.exists(args.env_path):
        print(f"No .env file found at {args.env_path} — nothing to migrate.", file=sys.stderr)
        return 1

    config = read_env_file(args.env_path)
    key = get_or_create_key(args.key_path)
    to_set, summary = plan_updates(config, key)

    new_password_hash = None
    if not config.get('WEB_CONFIG_PASSWORD_HASH') and not args.skip_password_prompt:
        new_password_hash = prompt_for_new_password_hash()
        if new_password_hash:
            to_set['WEB_CONFIG_PASSWORD_HASH'] = new_password_hash
            summary.append("Generated a new WEB_CONFIG_PASSWORD_HASH")

    if not summary:
        print("Nothing to migrate — .env is already up to date.")
    else:
        print("Planned changes:")
        for line in summary:
            print(f"  - {line}")

        if not args.yes:
            answer = input("\nApply these changes? [y/N] ").strip().lower()
            if answer != 'y':
                print("Aborted — no changes made.")
                return 0

        backup_path = f"{args.env_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(args.env_path, backup_path)
        print(f"Backed up existing .env to {backup_path}")

        atomic_write_env_file(args.env_path, to_set, [])
        print(f"Updated {args.env_path}")

    schedule_path = os.path.join(APP_DIR, 'schedule_config.json')
    schedule_example_path = os.path.join(APP_DIR, 'schedule_config.json.example')
    if not os.path.exists(schedule_path) and os.path.exists(schedule_example_path):
        shutil.copy2(schedule_example_path, schedule_path)
        print(f"Created {schedule_path} from schedule_config.json.example (edit it to customize your screen schedule)")

    return 0


if __name__ == '__main__':
    sys.exit(main())
