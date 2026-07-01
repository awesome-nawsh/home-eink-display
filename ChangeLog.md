# Changelog - Bus Arrival Display

## [V14] - Rewrite in progress (branch `v14-rewrite`)

### Phase 3 — `web_config.py` rewrite: session auth, scheduler UI, `/api/restart`, secrets at rest

Fixes a real auth bypass and closes out the last major file from before this rewrite. See `todo.md` for the full checklist.

- **Auth bypass fixed**: the previous "auth" was a bare unsigned cookie (`logged_in=true`) any client could forge to skip login entirely. Replaced with a real signed Flask `session` (itsdangerous, keyed by `app.secret_key`) — a tampered/forged cookie now fails signature verification. `WEB_CONFIG_SECRET_KEY`/`WEB_CONFIG_PASSWORD_HASH` no longer have insecure fallbacks; `web_config.py` refuses to start (`validate_web_config()`) if either is unset or a known placeholder.
- Minimal hand-rolled CSRF protection (session-stored token, checked on `/login`, `/save`, `/save_schedule`, `/api/restart`, `/api/refresh`) — no new dependency.
- **New `/schedule` + `/save_schedule`** — edits `schedule_config.json`'s four screen windows directly (`<input type="time">`), reusing `scheduler.validate_schedule()`/`detect_overlaps()` (never reimplemented). Surfaces schedule-conflict warnings in the UI — closes that `todo.md` item. Writes atomically (temp file + `os.replace()`).
- **New `/api/restart`** — actually restarts `bus_display` via `systemctl` (the old `/api/refresh` only ever triggered an MQTT data refresh, never a real restart despite the UI implying one). Requires a one-time sudoers entry — see `systemd/bus_display_restart.sudoers.example`, not auto-installed.
- **Secrets encryption at rest** (`app/secrets_vault.py`, new `cryptography` dependency): password-type `.env` fields (`API_KEY`, `GOOGLE_MAPS_API_KEY`, `ONEMAP_API_KEY`, `HOME_ASSISTANT_TOKEN`, `MQTT_PASSWORD`) are encrypted (`enc:` prefix) when saved through the web UI, decrypted transparently by `config.py` on read. Protects a leaked/shared/committed `.env` file in isolation — not a defense against full filesystem access to the device, since the key file (`app/.encryption_key`, gitignored) lives on the same disk. Existing plaintext values keep working untouched until re-saved once.
- `CONFIG_SCHEMA` updated for Phase 2: fixed stale `http://` API URL defaults, renamed `HOME_ASSISTANT_SLEEP_URL` field to `HOME_ASSISTANT_DASHBOARD_URL`, added a "Day-Type & Scheduler" category (including `FORCE_SCREEN` as a dropdown for quick testing), relabeled legacy `WAKE_HOUR`/`SLEEP_HOUR`/etc. as fallback-only.
- Rewrote as multiple small modules (`web_config_schema.py`, `web_config_env.py`, `web_config_schedule_forms.py`, `secrets_vault.py`) plus real Jinja templates (`app/templates/`) and static assets (`app/static/`), replacing the single inline-HTML-string file.
- New `systemd/web_config.service` — the panel now has its own persistent systemd unit instead of "run it separately."
- 39 new tests (`test_secrets_vault.py`, `test_web_config_env.py`, `test_web_config_schedule_forms.py`, `test_web_config_auth.py`) — the last of these includes the actual regression test for the fixed auth bug (a forged `logged_in=true` cookie, and a session cookie signed with the wrong secret, both correctly denied).
- Explicitly deferred: login rate-limiting/lockout (single-admin LAN app, low risk — conscious skip, see `todo.md`).
- New `tools/migrate_env.py` — migrates an existing `.env` to this phase's format (encrypts plaintext secrets, adds `HOME_ASSISTANT_DASHBOARD_URL`, generates `WEB_CONFIG_SECRET_KEY`/`WEB_CONFIG_PASSWORD_HASH` if missing, creates `schedule_config.json` from the template). Backs up `.env` first; never prints secret values.
- New [How-to.md](How-to.md) — step-by-step setup guide for running this project from scratch.

### Phase 2 — Four-screen scheduler, day-type gating, boot connectivity checklist

Replaces the single fixed `WAKE_HOUR`/`SLEEP_HOUR` pair and static "System Starting..." boot message. See `todo.md` for the full checklist and explicitly deferred items.

- `app/scheduler.py` — pure schedule logic (`load_schedule_config`, `validate_schedule`, `default_schedule_from_env`, `detect_overlaps`, `get_next_wake_time`, `resolve_active_screen`) driving four independently-scheduled screens defined in a new `schedule_config.json` (see `schedule_config.json.example`). Fixed precedence: `sleep_screen` > `bus_train_screen` > `daytime_screen` > `ha_screen`; overlaps are logged, not errors. Falls back to a schedule derived from the legacy `WAKE_HOUR`/`SLEEP_HOUR` if `schedule_config.json` is absent/invalid.
- `app/render/sleep_screen.py` (new) — the true overnight screen: minimal, locally-PIL-drawn (`MDI.WEATHER_NIGHT` icon + "Next wake: HH:MM"), no network fetch. Highest precedence of all four screens — the "ultimate override," never gated by day-type. While active, the main loop skips `fetch_data_parallel()` entirely, same as `ha_screen`.
- `app/day_type.py` + `fetchers.get_day_type_sensors()` — resolves `school_day`/`work_day`/`off_day` once per calendar day from `binary_sensor.school_day`/`binary_sensor.workday_sensor`, with a fallback if Home Assistant is unreachable. `bus_train_screen` is only eligible on `school_day`.
- `app/render/sleep_screen.py` (original) → renamed to `app/render/ha_screen.py` (`display_sleep_screen` → `display_ha_screen`) — same HA-dashboard-screenshot behavior, now driven by its own schedule entry. Moved to **lowest** precedence of the four — only shows in a genuine gap the other three don't claim. While `ha_screen` is active, the main loop skips `fetch_data_parallel()` entirely (no LTA/weather polling).
- `app/render/daytime_screen.py` (new) — placeholder screen ("Day time screen" centered); real content deferred.
- `app/boot_checks.py` + `app/render/boot_screen.py` (new) — boot-time connectivity checklist (Network/Internet/LTA API/Home Assistant), all four checks run before a single render+display() call.
- `config.py` — new vars: `HOME_ASSISTANT_SCHOOL_DAY_ENTITY`, `HOME_ASSISTANT_WORKDAY_ENTITY`, `DAY_TYPE_FALLBACK`, `SCHEDULE_CONFIG_PATH`, `BOOT_CHECK_TIMEOUT`, `INTERNET_CHECK_URL`, `HOME_ASSISTANT_DASHBOARD_URL` (falls back to legacy `HOME_ASSISTANT_SLEEP_URL`), `FORCE_SCREEN` (testing override — forces one screen regardless of schedule/day-type, invalid values logged and ignored). `WAKE_HOUR`/`SLEEP_HOUR` kept as the migration-fallback input to `default_schedule_from_env()`.
- `tests/` (new) — stdlib `unittest` coverage for `scheduler.py`, `day_type.py`, and `boot_checks.py`'s pure formatting function. Run via `python -m unittest discover -s tests`.
- `tools/preview_render.py` — added `--screen daytime`, `--screen sleep`, and `--screen boot` (fixed fake connectivity results, no network).
- **Known gaps carried into Phase 3**: `app/web_config.py`'s Schedule Settings section still references the legacy `WAKE_HOUR`/`SLEEP_HOUR`/`HOME_ASSISTANT_SLEEP_URL` vars, and schedule-conflict warnings are only logged (not shown in any UI) — both need the Phase 3 `web_config.py` rewrite. `tools/layout_editor.html` still uses the pre-rename `sleep_screen` naming (now ambiguous with the new true sleep screen — needs updating to disambiguate).

### Phase 1 — Module split (pure refactor, no behavior change)

`app/main.py` (~1600 lines, monolithic) is split into focused modules. Every function/class keeps its current name, signature, and logic — this phase changes only where code lives, not what it does.

- `app/config.py` — all environment variable loading, layout constants (`SCREEN_WIDTH`/`SCREEN_HEIGHT`/`COLUMN_OFFSET` and everything derived from them), `validate_configuration()`.
- `app/health.py` — `Watchdog`, `SystemHealth`.
- `app/fetchers.py` — `DataCache`, `BackoffManager`, the shared `http_session`, and every bus/train/weather/journey-time fetch function, `fetch_data_parallel()`.
- `app/mqtt_client.py` — `MQTTClient`.
- `app/render/common.py` — `MDI` icon table, font loaders, `DisplayManager`, `draw_mdi_icon`, `get_weather_icon`.
- `app/render/bus_train.py` — the awake-screen draw functions and `display_combined_view()`.
- `app/render/sleep_screen.py` — `display_sleep_screen()` (HA dashboard screenshot), name unchanged for this phase.
- `app/render/debug_screen.py` — `display_debug_screen()`.
- `app/main.py` — now orchestration only: startup validation, hardware init, boot screen, and the main loop, importing everything above.

`app/web_config.py` and `systemd/bus_display.service` are untouched by this phase.

This is Phase 1 of a larger, multi-phase rewrite (new screen types, a day-type-aware scheduler, `web_config.py` security/feature rewrite, dynamic config reload) — see `architecture.md`, `design.md` for the updated module layout, and later `[V14]` entries here as subsequent phases land.

## [V13] - 2025-01-XX

### 🎯 Major Features

#### API-Based Journey Time Calculation
- **NEW**: Integrated routing APIs to calculate real journey times to destination
- Supports two routing providers:
  - OneMap API (free, Singapore-based)
  - Google Maps Directions API (requires API key)
- Calculates total journey time including:
  - Wait time for bus arrival
  - Transit time from bus stop to destination
  - Estimated arrival time at destination

#### Journey Time Configuration
- Added `SHOW_JOURNEY_TIME` feature flag
- `BUS_SERVICES_TO_TRACK` - specify which bus services to track
- `JOURNEY_DESTINATION` - set destination address/location
- `JOURNEY_DESTINATION_SHORT` - optional short display name
- `ROUTING_API_PROVIDER` - choose between 'onemap' or 'google'
- `GOOGLE_MAPS_API_KEY` - for Google Maps integration
- `ONEMAP_API_KEY` - optional OneMap API token
- `JOURNEY_TIME_CACHE_DURATION` - cache routing results (default 30min)

### 🔧 Technical Improvements

#### API Integration
- `get_bus_stop_coordinates()` - fetch lat/lon from LTA DataMall
- `calculate_journey_time_onemap()` - OneMap routing integration
- `calculate_journey_time_google()` - Google Maps routing integration
- `calculate_journey_times_with_api()` - orchestrates journey calculations
- Intelligent caching for routing results (30min default vs 20s for bus data)

#### System Health & Monitoring
- Enhanced `SystemHealth` class with routing API metrics
- Track API calls for: bus, train, weather, and routing
- Separate error counters per API type
- `system_health.record_api_call()` tracks success/failure rates

#### Display Enhancements
- `draw_bus_section()` now displays journey times below bus boxes
- Shows destination, total time, and arrival time estimate
- Uses Material Design Icons for journey indicators
- Red text for journey info (better visibility on e-ink)
- Simplified journey display format

#### Code Organization
- Added MDI icons: `MAP_MARKER_DISTANCE`, `TIMER`, `NAVIGATION`
- Better separation of concerns between data fetching and journey calculation
- `fetch_data_parallel()` now returns journey_times as 4th value
- Journey calculations run after bus data is fetched (more efficient)

### 🐛 Bug Fixes & Improvements
- Fixed parallel data fetching to handle journey time dependencies
- Improved error handling for routing API failures
- Better backoff management for routing API calls
- Enhanced logging for journey time calculations

### 📝 Configuration
- Added validation for journey time configuration
- Warns if journey tracking enabled without proper setup
- Validates Google Maps API key when Google provider selected
- Better .env documentation with examples

### 🔄 API Changes
- `display_combined_view()` now accepts `journey_times` parameter
- `draw_bus_section()` signature updated with journey_times
- `fetch_data_parallel()` returns 4-tuple instead of 3-tuple

---

## [V12] - Previous Version

### Features from V12 (for reference)
- MQTT integration for Home Assistant
- Parallel API data fetching
- Weather integration from Home Assistant
- Sleep screen with dashboard screenshots
- System health monitoring
- Watchdog for hung processes
- Backoff manager for failed API calls
- Debug mode with configuration display
- Material Design Icons integration
- Two-column layout (buses + trains)
- Cache management with configurable durations

---

## Migration from V12 to V13

### Required Changes
1. Update `.env` file with new journey time variables:
```env
   SHOW_JOURNEY_TIME=true
   BUS_SERVICES_TO_TRACK="970,156,77"
   JOURNEY_DESTINATION="Your Destination"
   ROUTING_API_PROVIDER="onemap"
   JOURNEY_TIME_CACHE_DURATION=1800
