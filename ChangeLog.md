# Changelog - Bus Arrival Display

## [V15.1] - Web panel status bar shows its own uptime

- The status bar's "Web Panel" cell now shows how long `web_config.py` itself has been running, alongside the existing "Display Service" cell for `bus_display`. `/api/status` gained a `web_config` key (`uptime_seconds`/`uptime_formatted`) computed from a module-level start timestamp recorded at import — no shared file needed, since the process serving the request *is* the thing being reported on. New test: 138 total.

## [V15] - Daytime word clock, weather fallback, font chooser, web UI polish

- **Real `daytime_screen` content** (was a "Day time screen" placeholder): a word clock ("Quarter past two"), the date, and current weather. Deliberately quarter-hour-granular — a full e-ink refresh is slow and flashes the panel, so it redraws only when the quarter-hour bucket or the weather changes: 4 refreshes/hour, aligned to :00/:15/:30/:45 (each lands within one ~30s loop tick of the boundary). The pure model half (`build_daytime_model()`/`time_in_words()`) is unit-tested; `tools/preview_render.py --screen daytime` previews it.
- **Open-Meteo weather fallback** (free, no API key): weather no longer silently disappears when Home Assistant is unconfigured or down. New `get_weather()` chains HA → Open-Meteo → stale cache behind the same single cache key and backoff (a failure is recorded only when *both* sources fail). Location comes from new optional `WEATHER_LAT`/`WEATHER_LON`, else the bus stop's own coordinates. A pure WMO-code→condition mapping keeps both sources speaking HA's condition vocabulary.
- **Font chooser**: `DISPLAY_FONT` in `.env` (or the web panel's "Display & Fonts" section) picks the display typeface from `render/common.py`'s `FONT_REGISTRY` — three Atkinson weight pairings, general-purpose OFL statics of **Inter**, **IBM Plex Sans**, and **Noto Sans**, plus four e-ink-oriented faces: **Bitter** (slab serif designed for e-readers), **Literata** (Google Play Books' e-reading serif), **Lexend** (legibility-research sans), and **Fira Sans** (designed for low-resolution screens) — ten options total, each in `pic/<family>/` with its `OFL.txt`. Unknown names/missing files fall back to Atkinson Regular with a warning. Restart-required, like most `.env` values. The MDI icon font is untouched. The dropdown shows a live, server-rendered sample (`/api/font_sample/<name>`) underneath — drawn with the exact pipeline the panel uses, not a browser webfont approximation — so you can see a typeface before committing to a restart.
- **Web UI polish**: Settings categories reordered by how often they're actually touched — day-to-day knobs first, and a new **Advanced** card (LTA API URLs, boot-check knobs) that renders collapsed by default. All cards are now collapsible (`<details>`/`<summary>`, no JS). Fixed the `FORCE_SCREEN` dropdown showing two blank options ("-- Select --" and "(none)"). Screen identifiers (`sleep_screen`, `bus_train_screen`, ...) are now shown as friendly labels ("Overnight (Sleep Screen)", "Bus & Train", ...) on the Schedule page and in the `FORCE_SCREEN` dropdown — purely cosmetic, the stored/submitted values are unchanged.
- **Air quality**: shown next to humidity on the `bus_train_screen` weather section and in the `daytime_screen` detail line (with its category there, e.g. "AQI 57 (Moderate)"). Same two-source shape as weather: the household's own HA sensors first (`HOME_ASSISTANT_AQI_ENTITY` + optional `HOME_ASSISTANT_AQI_CATEGORY_ENTITY`), falling back to NEA's public 24-hour PSI (data.gov.sg, free, no key — worst of the five regional readings). The reading rides along inside the weather dict (fetched/cached with it); an air-quality fetch failure just hides it, never breaks weather. A reading change also triggers a daytime redraw.
- **ha_screen can now be disabled**: a new "Enabled" checkbox on the Schedule page switches `ha_screen` off entirely without losing its configured start/end times. A disabled `ha_screen` is treated as if its window never matched — any gap it would have claimed falls through to `daytime_screen`. The other three screens don't get this toggle; each is load-bearing (`daytime_screen` in particular is the scheduler's final fallback for any uncovered moment).
- **Bug fixes**: the web panel's "Refresh" and schedule-save MQTT publishes now decrypt a vault-encrypted `MQTT_PASSWORD` before handing it to the broker (previously sent the `enc:...` ciphertext straight through, which the broker rejected as "Not authorized"). `/api/restart` now uses `systemctl restart --no-block`, which queues the restart and returns immediately instead of blocking the HTTP request on `bus_display`'s full stop+start cycle — the old blocking call could exceed a short HTTP timeout even when nothing was actually wrong (existing deployments need to re-run the sudoers install step to pick up the new command).
- New tests: `test_weather.py`, `test_daytime_model.py`, `test_fonts.py`, `test_web_config_schema.py`, plus expanded coverage in `test_scheduler.py`, `test_web_config_schedule_forms.py`, and `test_web_config_auth.py` (137 total).

## [V14] - Rewrite in progress (branch `v14-rewrite`)

### Post-Phase-4 review pass (branch `v14-review-fixes`)

A three-reviewer code audit of the whole codebase (comments/readability, Pi-Zero efficiency, stale/redundant code), with each fix individually approved before implementation.

**Bug fixes:**
- A failed `ha_screen` dashboard fetch now genuinely retries on the next tick — previously the screen was marked active anyway, so the "will retry" log message was a lie and the panel kept the previous image until the window ended.
- `get_bus_stop_coordinates()` no longer memoizes a failed lookup — a transient network blip during the first journey calculation used to disable journey times until a service restart (`lru_cache` cached the `None`).
- The web UI's "applies live — no restart needed" flash message can now actually appear: `save_config` diffs submitted values against the current `.env` instead of counting every field as changed on every save.
- `paho-mqtt` pinned `>=2.0` and `mqtt_client.py` migrated to the v2 callback API — fresh installs get paho 2.x, where the old v1 constructor call crashed at startup. Also `connect_async()` so a broker that's down at boot self-heals when it returns (previously MQTT stayed dead for the life of the process).

**Resilience:**
- **Stale-data policy** (new `STALE_DATA_MAX_AGE`, default 600s): during an LTA outage, bus/train keep showing last-known-good data up to that age, then the display shows an explicit "data unavailable" error for that section — previously it silently went blank after 20 seconds. A genuinely empty response (no buses running) still renders blank; it's data, not an error. Weather serves stale readings indefinitely (ages gracefully) via the same new `DataCache.get_stale()` API instead of poking cache internals.
- **Real watchdog**: the in-process `Watchdog` class was structurally inert (fed and checked itself from the same thread — could never detect a hang) and is replaced by systemd's `Type=notify` + `WatchdogSec=900` with `sd_notify('WATCHDOG=1')` pings from the loop. Deploying this needs `sudo systemctl daemon-reload` after pulling the new unit file.
- The journey-time cache no longer grows unboundedly (timestamped keys are pruned each cycle), and `fetch_data_parallel()` reuses one thread pool instead of creating one per tick.

**New: live service status in the web panel** — `main.py` writes a per-tick health snapshot (uptime, active screen, day-type, MQTT state, API counters) to `STATUS_FILE_PATH` (default `/tmp/bus_display_status.json`); `/api/status` serves it and the Settings page status bar shows it (replacing a hardcoded "✓ Loaded").

**Renames/config:**
- `SLEEP_SCREEN_*` → `HA_SCREEN_*` (these six vars configure `ha_screen`, not the true sleep screen). Old names still read as fallbacks; `tools/migrate_env.py` copies them forward; the web UI gains an "ha_screen (Dashboard Screenshot)" section. The previously-dead `SLEEP_SCREEN_FORMAT` is now actually used (as `HA_SCREEN_FORMAT`).
- The debug screen shows the real `schedule_config.json` windows and today's resolved day-type instead of legacy `WAKE_HOUR`/`SLEEP_HOUR` and hardcoded "APIs configured"/"Routing ready" filler.

**Web hardening:** CSRF is now default-deny (every POST checked unless explicitly exempted); `/logout` is a CSRF-protected POST instead of a GET a cross-site image tag could trigger.

**Cleanups:** overlap warnings computed once per schedule load instead of every 30s tick (`resolve_active_screen()` now returns just the screen name); the duplicated debug/bus-train fetch-render block in `main.py` extracted to one helper; assorted stale comments fixed (ha_screen precedence docstring, pre-Phase-4 restart claims, leftover truncation marker); bare `except:` → `except OSError` in font loaders; `KNOWN_BAD_SECRET_KEYS` shared from one module; a tautological scheduler test now asserts a real value.

### Phase 4 — Dynamic (no-restart) config reload for the schedule and `FORCE_SCREEN`

Since Phase 1, config is loaded once at process start; changing anything meant a restart (a one-click action since Phase 3's `/api/restart`, but still a restart). This phase makes exactly two things reloadable live, without one — deliberately not "everything," since retrofitting dotted `config.SOMEVAR` lookups across every module for variables nobody's asked to change without a restart would be a large, invasive rewrite for no real benefit. See `design.md` §15 for the full rationale.

- `app/reload_watch.py` (new) — pure `get_mtime()`/`has_changed()` file-change detection, used as the mtime-poll backstop.
- `config.py` — `DYNAMIC_CONFIG_VARS = ('FORCE_SCREEN',)`, `reload_dynamic_vars()` (re-reads `.env`, refreshes `FORCE_SCREEN` in place), `config_reload_requested` event, new `MQTT_TOPIC_CONFIG_RELOAD` var, explicit `ENV_FILE_PATH` constant (replacing the implicit `load_dotenv()` search).
- `mqtt_client.py` — subscribes to `MQTT_TOPIC_CONFIG_RELOAD`; any message sets `config_reload_requested`.
- `main.py` — each loop tick, checks `config_reload_requested` and the `.env`/`schedule_config.json` mtimes; reloads the schedule and/or `config.FORCE_SCREEN` (now read via dotted access, not a bare imported name, so it actually sees live updates) as needed.
- `web_config.py` — saving the schedule now auto-publishes an MQTT `config_reload` message (no more "restart to apply" for schedule changes); saving only `FORCE_SCREEN` via the Settings page does the same. Everything else still needs a restart.
- `web_config_schema.py`/`_field_macros.html` — `FORCE_SCREEN` is marked `'dynamic': True`, rendered with an "applies live" badge in the Settings UI.
- New tests: `test_reload_watch.py`, `test_config_force_screen.py`.
- Explicitly deferred (see `todo.md`): expanding `DYNAMIC_CONFIG_VARS` to more variables.

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
