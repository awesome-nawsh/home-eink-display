#!/usr/bin/env python3
"""
E-ink Display Web Configuration Panel
A Flask web interface to manage .env / schedule_config.json without SSH.

Auth: real signed Flask `session` (itsdangerous, keyed by app.secret_key) —
NOT a bare cookie check. A tampered/forged cookie fails signature
verification and is treated as an empty (logged-out) session. See
validate_web_config() for the startup guard that refuses to run with a
placeholder secret key or default password.
"""
import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, session,
)
from werkzeug.security import check_password_hash
import paho.mqtt.publish as mqtt_publish

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from scheduler import load_schedule_config, validate_schedule, detect_overlaps
from secrets_vault import get_or_create_key, encrypt_value, decrypt_value
from web_config_schema import CONFIG_SCHEMA, COLLAPSED_CATEGORIES
from web_config_env import read_env_file, build_env_updates, atomic_write_env_file, KNOWN_BAD_SECRET_KEYS
from web_config_schedule_forms import schedule_from_form, atomic_write_json

from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.realpath(__file__))
ENV_FILE = os.path.join(APP_DIR, '.env')
load_dotenv(ENV_FILE)

app = Flask(__name__)

# --- Configuration -----------------------------------------------------
WEB_CONFIG_PORT = int(os.getenv('WEB_CONFIG_PORT', '5000'))
WEB_CONFIG_HOST = os.getenv('WEB_CONFIG_HOST', '0.0.0.0')
WEB_CONFIG_USERNAME = os.getenv('WEB_CONFIG_USERNAME', 'admin')
# No hardcoded fallbacks for either of these — an unset value means
# validate_web_config() refuses to start rather than running with a
# well-known secret/password.
WEB_CONFIG_SECRET_KEY = os.getenv('WEB_CONFIG_SECRET_KEY', '')
WEB_CONFIG_PASSWORD_HASH = os.getenv('WEB_CONFIG_PASSWORD_HASH', '')

SCHEDULE_CONFIG_PATH = os.getenv(
    'SCHEDULE_CONFIG_PATH', os.path.join(APP_DIR, 'schedule_config.json')
)
WAKE_HOUR = int(os.getenv('WAKE_HOUR', '7'))
SLEEP_HOUR = int(os.getenv('SLEEP_HOUR', '22'))

SECRETS_KEY_PATH = os.getenv('SECRETS_KEY_PATH', os.path.join(APP_DIR, '.encryption_key'))
# Must match config.py's default — where main.py drops its health snapshot
STATUS_FILE_PATH = os.getenv('STATUS_FILE_PATH', '/tmp/bus_display_status.json')

app.secret_key = WEB_CONFIG_SECRET_KEY
app.permanent_session_lifetime = timedelta(hours=8)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# SESSION_COOKIE_SECURE deliberately left unset/False: this runs over plain
# HTTP on a LAN, no TLS. Setting it True would break login entirely.


def validate_web_config():
    """Startup guard: refuses to start with a placeholder secret key or an
    unset password hash (which would otherwise silently fall back to a
    well-known default password). Mirrors config.py's validate_configuration()."""
    errors = []
    if WEB_CONFIG_SECRET_KEY in KNOWN_BAD_SECRET_KEYS:
        errors.append("WEB_CONFIG_SECRET_KEY is unset or is a known placeholder value")
    if not WEB_CONFIG_PASSWORD_HASH:
        errors.append("WEB_CONFIG_PASSWORD_HASH is unset (would otherwise default to a well-known password)")

    if not errors:
        return True

    print("=" * 60, file=sys.stderr)
    print("web_config.py refuses to start with insecure defaults:", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    print(file=sys.stderr)
    print("Generate a secret key with:", file=sys.stderr)
    print('  python3 -c "import secrets; print(secrets.token_hex(32))"', file=sys.stderr)
    print("Generate a password hash with:", file=sys.stderr)
    print('  python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash(\'your_password\'))"', file=sys.stderr)
    print("Add both to app/.env as WEB_CONFIG_SECRET_KEY= and WEB_CONFIG_PASSWORD_HASH=", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    return False


def check_auth(username, password):
    if not WEB_CONFIG_PASSWORD_HASH:
        return False
    try:
        return username == WEB_CONFIG_USERNAME and check_password_hash(WEB_CONFIG_PASSWORD_HASH, password)
    except ValueError:
        return False


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
            return redirect(url_for('index'))
        return view(*args, **kwargs)
    return wrapped


# --- CSRF ----------------------------------------------------------------
# Every POST is CSRF-checked unless its endpoint is explicitly exempted here
# (default-deny: a future route added without thinking about CSRF ships
# protected, instead of silently unprotected as with the old allowlist).
CSRF_EXEMPT_ENDPOINTS = set()


def get_csrf_token():
    """Generates and stores a per-session CSRF token if one doesn't exist
    yet, so it's available before login (the login form itself needs one)."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']


@app.before_request
def check_csrf():
    if request.method != 'POST' or request.endpoint in CSRF_EXEMPT_ENDPOINTS:
        return None
    submitted = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    expected = session.get('csrf_token', '')
    if not expected or not secrets.compare_digest(submitted, expected):
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Invalid or missing CSRF token'}), 400
        flash('Your session expired or the form was resubmitted — please try again.', 'error')
        return redirect(url_for('index'))
    return None


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': get_csrf_token()}


# --- Routes ----------------------------------------------------------------
@app.route('/')
def index():
    if not session.get('logged_in'):
        return render_template('login.html')

    config = read_env_file(ENV_FILE)
    last_updated = (
        datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).strftime('%Y-%m-%d %H:%M')
        if os.path.exists(ENV_FILE) else 'Never'
    )
    return render_template(
        'index.html', config=config, config_schema=CONFIG_SCHEMA, last_updated=last_updated,
        collapsed_categories=COLLAPSED_CATEGORIES,
    )


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    if check_auth(username, password):
        session.clear()
        session['logged_in'] = True
        session.permanent = True
        flash('Successfully logged in!', 'success')
    else:
        flash('Invalid username or password', 'error')
    return redirect(url_for('index'))


@app.route('/logout', methods=['POST'])
def logout():
    # POST (not GET) so a cross-site <img src="/logout"> can't force-logout;
    # covered by the default-deny CSRF check like every other POST.
    session.clear()
    flash('Successfully logged out', 'info')
    return redirect(url_for('index'))


def _mqtt_auth():
    """Broker auth dict for the publish helpers below, or None when no
    credentials are configured. MQTT_PASSWORD in .env may be vault-encrypted
    (enc: prefix, saved that way by this very UI) — decrypt it the same way
    config.py does for the main process; decrypt_value() passes plaintext
    values through unchanged."""
    username = os.getenv('MQTT_USERNAME')
    password = os.getenv('MQTT_PASSWORD')
    if not (username and password):
        return None
    return {'username': username,
            'password': decrypt_value(password, get_or_create_key(SECRETS_KEY_PATH))}


def publish_config_reload():
    """Best-effort MQTT ping telling the running bus_display process to
    reload its dynamic config (schedule + FORCE_SCREEN) immediately, rather
    than waiting for its mtime-poll backstop. Never raises — a failed
    publish just means that backstop picks the change up a bit later instead."""
    try:
        mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        mqtt_port = int(os.getenv('MQTT_PORT', '1883'))
        mqtt_topic = os.getenv('MQTT_TOPIC_CONFIG_RELOAD', 'eink/display/config_reload')

        mqtt_publish.single(mqtt_topic, 'reload', hostname=mqtt_broker, port=mqtt_port, auth=_mqtt_auth())
    except Exception as e:
        logging.warning(f"Could not publish config_reload via MQTT: {e}")


# Fields that main.py can pick up live, without a restart — see
# config.DYNAMIC_CONFIG_VARS. Kept here as a literal (rather than importing
# config.py, which this standalone process otherwise avoids) since it's
# purely a UI/messaging concern, not shared runtime state.
DYNAMIC_ENV_FIELDS = {'FORCE_SCREEN'}


@app.route('/save', methods=['POST'])
@login_required
def save_config():
    secrets_key = get_or_create_key(SECRETS_KEY_PATH)

    def encrypt_fn(value):
        return encrypt_value(value, secrets_key)

    to_set, to_unset = build_env_updates(request.form, CONFIG_SCHEMA, encrypt_fn)

    # build_env_updates() returns EVERY schema field on every save (checkboxes
    # always resolve to true/false, blanks always land in to_unset) — so diff
    # against the current .env to find what the user actually changed, or the
    # dynamic-vs-restart messaging below is meaningless. Password fields are
    # the exception: a non-blank submission always counts as changed (Fernet
    # ciphertexts differ every encryption, and typing one is intentional).
    current = read_env_file(ENV_FILE)
    changed_fields = {k for k, v in to_set.items() if current.get(k) != v}
    changed_fields |= {k for k in to_unset if k in current}

    try:
        atomic_write_env_file(ENV_FILE, to_set, to_unset)
        if changed_fields & DYNAMIC_ENV_FIELDS:
            publish_config_reload()
        if not changed_fields:
            flash('No changes to save.', 'info')
        elif changed_fields <= DYNAMIC_ENV_FIELDS:
            flash('Configuration saved — applies automatically within moments (no restart needed).', 'success')
        else:
            flash('Configuration saved. Restart the service to apply changes.', 'success')
    except OSError as e:
        flash(f'Error saving configuration: {e}', 'error')

    return redirect(url_for('index'))


@app.route('/schedule')
@login_required
def schedule_page():
    schedule = load_schedule_config(SCHEDULE_CONFIG_PATH, WAKE_HOUR, SLEEP_HOUR)
    warnings = detect_overlaps(schedule)
    return render_template('schedule.html', schedule=schedule, warnings=warnings)


@app.route('/save_schedule', methods=['POST'])
@login_required
def save_schedule():
    candidate = schedule_from_form(request.form)
    errors = validate_schedule(candidate)
    if errors:
        for e in errors:
            flash(e, 'error')
        return redirect(url_for('schedule_page'))

    try:
        atomic_write_json(SCHEDULE_CONFIG_PATH, candidate)
    except OSError as e:
        flash(f'Error saving schedule: {e}', 'error')
        return redirect(url_for('schedule_page'))

    publish_config_reload()

    for w in detect_overlaps(candidate):
        flash(w, 'info')
    flash('Schedule saved — applies automatically within moments (no restart needed).', 'success')
    return redirect(url_for('schedule_page'))


@app.route('/api/refresh', methods=['POST'])
@login_required
def api_refresh():
    """Trigger an immediate data refresh via MQTT (no service restart)."""
    try:
        mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        mqtt_port = int(os.getenv('MQTT_PORT', '1883'))
        mqtt_topic = os.getenv('MQTT_TOPIC_REFRESH', 'eink/display/refresh')

        mqtt_publish.single(mqtt_topic, 'refresh', hostname=mqtt_broker, port=mqtt_port, auth=_mqtt_auth())
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/restart', methods=['POST'])
@login_required
def api_restart():
    """Restart the bus_display systemd service — required for most .env
    changes to take effect (config is loaded once at process start; the
    schedule and FORCE_SCREEN are the exceptions, applying live via the
    config_reload mechanism). Requires a one-time passwordless-sudo setup;
    see systemd/bus_display_restart.sudoers.example."""
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'restart', 'bus_display'],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return jsonify({'success': True})
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Restart command timed out after 15s. Check `systemctl status bus_display` on the Pi.',
        }), 500
    except subprocess.CalledProcessError as e:
        return jsonify({
            'success': False,
            'error': (
                'Restart failed (permission denied or systemctl error). This requires a '
                'one-time passwordless-sudo setup — see systemd/bus_display_restart.sudoers.example. '
                f'Details: {(e.stderr or e.stdout or "").strip()}'
            ),
        }), 500
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'sudo or systemctl not found on this system'}), 500


@app.route('/api/status')
@login_required
def api_status():
    """Config-file status plus the display process's own health report.
    main.py writes the report to STATUS_FILE_PATH every loop tick (the two
    run as separate processes, so a small JSON file is the shared channel);
    'display' is null if the file doesn't exist yet or can't be parsed —
    the status bar shows that as "no status reported"."""
    display_status = None
    try:
        with open(STATUS_FILE_PATH) as f:
            display_status = json.load(f)
    except (OSError, ValueError):
        pass
    return jsonify({
        'config_exists': os.path.exists(ENV_FILE),
        'last_modified': (
            datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).isoformat()
            if os.path.exists(ENV_FILE) else None
        ),
        'display': display_status,
    })


if __name__ == '__main__':
    if not validate_web_config():
        sys.exit(1)

    print("=" * 60)
    print("E-ink Display Web Configuration Panel")
    print("=" * 60)
    print(f"\n🌐 Access at: http://{WEB_CONFIG_HOST}:{WEB_CONFIG_PORT}")
    print(f"👤 Username: {WEB_CONFIG_USERNAME}")
    print("\n" + "=" * 60 + "\n")

    app.run(host=WEB_CONFIG_HOST, port=WEB_CONFIG_PORT, debug=False)
