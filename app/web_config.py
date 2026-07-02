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
    send_file,
)
from werkzeug.security import check_password_hash
import paho.mqtt.publish as mqtt_publish

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from scheduler import (
    load_schedule_config, validate_schedule, detect_overlaps,
    SCREEN_DISPLAY_NAMES, DISABLEABLE_SCREENS,
)
from secrets_vault import get_or_create_key, encrypt_value, decrypt_value
from web_config_schema import CONFIG_SCHEMA, COLLAPSED_CATEGORIES
from web_config_env import read_env_file, build_env_updates, atomic_write_env_file, KNOWN_BAD_SECRET_KEYS
from web_config_schedule_forms import schedule_from_form, atomic_write_json

from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.realpath(__file__))
ENV_FILE = os.path.join(APP_DIR, '.env')
load_dotenv(ENV_FILE)

# tools/preview_render.py has no hardware imports (same as app/render/*.py
# and app/config.py — see its own docstring) so it's safe to import directly
# into this process for the Preview tab's /api/preview_image route.
TOOLS_DIR = os.path.join(os.path.dirname(APP_DIR), 'tools')

# Friendly labels for the Preview tab's screen picker. combined/daytime/sleep
# reuse scheduler.SCREEN_DISPLAY_NAMES so the wording matches the Schedule
# page; boot/debug aren't scheduled screens, so they get their own labels.
PREVIEW_SCREEN_LABELS = {
    'combined': SCREEN_DISPLAY_NAMES['bus_train_screen'],
    'daytime': SCREEN_DISPLAY_NAMES['daytime_screen'],
    'sleep': SCREEN_DISPLAY_NAMES['sleep_screen'],
    'boot': 'Boot Checklist',
    'debug': 'Debug Dump',
}

# Process start time, for the status bar's "Web Panel" uptime — recorded at
# import rather than inside a request handler, so it reflects when this
# process actually started (a Flask reload/worker respawn resets it, which
# is the correct signal here, distinct from bus_display's own uptime).
WEB_CONFIG_START_TIME = datetime.now()

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
    return render_template(
        'schedule.html', schedule=schedule, warnings=warnings,
        screen_display_names=SCREEN_DISPLAY_NAMES, disableable_screens=DISABLEABLE_SCREENS,
    )


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


@app.route('/api/font_sample/<font_name>')
@login_required
def api_font_sample(font_name):
    """A PIL-rendered text sample of one FONT_REGISTRY entry, drawn with the
    exact rendering pipeline the e-ink display uses (not a browser webfont
    approximation). Shown under the DISPLAY_FONT dropdown, swapped live by
    web_config.js as the selection changes."""
    # Lazy imports: PIL and the render package are only needed here, not for
    # the rest of the panel's startup.
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    from render.common import FONT_REGISTRY, resolve_font_pair

    if font_name not in FONT_REGISTRY:
        return jsonify({'success': False, 'error': 'Unknown font'}), 404

    regular_path, bold_path = resolve_font_pair(font_name)
    img = Image.new('RGB', (620, 116), 'white')
    d = ImageDraw.Draw(img)
    d.text((12, 8), 'Quarter past two', font=ImageFont.truetype(bold_path, 42), fill='black')
    d.text((12, 66), 'Thursday 2 July · 29°C · Humidity 68% · 0123456789',
           font=ImageFont.truetype(regular_path, 22), fill='black')

    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', max_age=3600)


@app.route('/preview')
@login_required
def preview_page():
    """The Preview tab: pick a screen + a few scenario toggles, see the
    render below (via /api/preview_image). ha_screen isn't offered — it
    fetches a live HA dashboard screenshot, not something to fake here."""
    return render_template('preview.html', screen_labels=PREVIEW_SCREEN_LABELS)


@app.route('/api/preview_image')
@login_required
def api_preview_image():
    """Renders one of the local (non-HA) screens to a PNG, using the exact
    same code path as `tools/preview_render.py` — the real render.* draw
    functions against a fake in-memory display, no e-ink hardware touched.
    Lets the Preview tab show what a screen looks like without SSHing in
    to run the CLI tool or waiting for its scheduled window on the Pi."""
    from io import BytesIO
    from types import SimpleNamespace
    sys.path.insert(0, TOOLS_DIR)
    import preview_render

    screen = request.args.get('screen', 'combined')
    if screen not in preview_render.SCREEN_RENDERERS:
        return jsonify({'success': False, 'error': 'Unknown screen'}), 404

    def flag(name):
        return request.args.get(name) == '1'

    args = SimpleNamespace(
        disruption=flag('disruption'),
        no_weather=flag('no_weather'),
        no_journey=flag('no_journey'),
        manual_refresh=flag('manual_refresh'),
    )
    mgr = preview_render.SCREEN_RENDERERS[screen](args)
    img = preview_render.composite_preview(mgr)

    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@app.route('/api/restart', methods=['POST'])
@login_required
def api_restart():
    """Queue a restart of the bus_display systemd service — required for most
    .env changes to take effect (config is loaded once at process start; the
    schedule and FORCE_SCREEN are the exceptions, applying live via the
    config_reload mechanism). Requires a one-time passwordless-sudo setup;
    see systemd/bus_display_restart.sudoers.example.

    Uses `--no-block` so this request returns as soon as the job is queued,
    rather than waiting for bus_display to fully stop and come back up —
    `systemctl restart` (no --no-block) blocks the whole request on that,
    and its shutdown path (MQTT disconnect, e-ink cleanup) can comfortably
    exceed a short HTTP timeout even though nothing is actually wrong. The
    status bar's uptime is what confirms the restart actually completed."""
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'restart', '--no-block', 'bus_display'],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return jsonify({'success': True})
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Could not queue the restart (sudo/systemctl unresponsive). Check `systemctl status bus_display` on the Pi.',
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
    """Config-file status, this panel's own uptime, plus the display
    process's own health report. main.py writes the report to
    STATUS_FILE_PATH every loop tick (the two run as separate processes,
    so a small JSON file is the shared channel); 'display' is null if the
    file doesn't exist yet or can't be parsed — the status bar shows that
    as "no status reported". 'web_config' needs no such file — this process
    computes its own uptime directly from WEB_CONFIG_START_TIME."""
    display_status = None
    try:
        with open(STATUS_FILE_PATH) as f:
            display_status = json.load(f)
    except (OSError, ValueError):
        pass
    web_uptime_seconds = int((datetime.now() - WEB_CONFIG_START_TIME).total_seconds())
    return jsonify({
        'config_exists': os.path.exists(ENV_FILE),
        'web_config': {
            'uptime_seconds': web_uptime_seconds,
            'uptime_formatted': str(timedelta(seconds=web_uptime_seconds)),
        },
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
