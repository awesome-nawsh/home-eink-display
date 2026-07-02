# Architecture — home-eink-display

Technical breakdown of how the system is put together. Companion to [specifications.md](specifications.md) (what it does) and [design.md](design.md) (why it's built this way).

---

## 1. System Overview

```
                     ┌─────────────────────────────────────────────┐
                     │              Raspberry Pi Zero W              │
                     │                                               │
  LTA DataMall  ───► │  app/main.py  (systemd: bus_display.service)  │ ───► Waveshare 7.5"
  (bus/train)        │                                               │      e-ink panel
                      │  ┌─────────┐  ┌──────────────┐  ┌─────────┐  │      (B/W/R, SPI/GPIO)
  OneMap /     ───►   │  │ fetchers │→│ display_combined│→│ EPD     │  │
  Google Maps          │  │ (parallel)│  │_view() draw fns│  │ driver  │  │
  (routing)            │  └─────────┘  └──────────────┘  └─────────┘  │
                      │        ▲                                      │
  Home Assistant ───► │        │  MQTT (refresh cmd, status pub)      │
  (weather,           │        │                                      │
  dashboard            │  ┌──────────┐                                │
  screenshot,          │  │MQTTClient│◄───────────────────────────────┼── Home Assistant
  MQTT broker)         │  └──────────┘                                │   (or any MQTT publisher)
                     │                                               │
                     │  app/web_config.py (optional, separate         │
                     │  process, Flask on :5000) — edits .env only    │
                     └─────────────────────────────────────────────┘
```

`app/main.py` is a single long-running process, started and supervised by systemd. It's the entry point for one process that owns the render loop, all API calls, MQTT, and direct hardware access to the e-ink panel via `lib/waveshare_epd/epd7in5b_V2.py` — as of the v14 module split, `main.py` itself is thin orchestration only, importing config/fetching/rendering logic from sibling modules (§3). `app/web_config.py` is a separate Flask process, now with its own systemd unit (`systemd/web_config.service`) — it reads/writes `.env` and `schedule_config.json`, and can trigger a real restart of the main service via `/api/restart`; it holds no runtime state of its own and does not talk to the display directly.

## 2. Process & Deployment Topology

- **Runtime**: single Python 3 process per service, no containers, no supervisor besides systemd.
- **`bus_display.service`** (deployed to `/etc/systemd/system/`): runs `app/main.py` as user `pi`, group `gpio`, with `SupplementaryGroups=gpio spi i2c` for hardware access. `Type=notify` + `WatchdogSec=900`: the loop pings `sd_notify('WATCHDOG=1')` every tick, and systemd kills and restarts the process if the pings stop (a real hang detector — the old in-process `Watchdog` class checked itself from the same thread and could never fire). `Restart=on-failure`, `RestartSec=10` (see [design.md](design.md) §7).
- **`web_config.py`** has its own systemd unit, `systemd/web_config.service`, deployed the same way as `bus_display.service` (manual copy to `/etc/systemd/system/`, per `CLAUDE.md`). Its `/api/restart` endpoint needs a one-time sudoers entry (`systemd/bus_display_restart.sudoers.example`) to restart `bus_display` without a password.
- **Dependencies**: Python packages via `pip` (`requirements.txt`); `pigpio`/`pigpiod` installed via `apt` (not pip-installable on Pi in a usable form) and must be running (`bus_display.service` has `Wants=pigpiod.service`, `After=pigpiod.service`).
- **Fonts**: loaded at runtime from `pic/` via absolute paths resolved from the script's own directory. The display typeface is chosen by `DISPLAY_FONT` from `render/common.py`'s `FONT_REGISTRY` (Atkinson Hyperlegible Next weight pairings, plus bundled OFL statics of Inter, IBM Plex Sans, and Noto Sans — each family ships its `OFL.txt`); icons always come from the Material Design Icons `.ttf`.
- **Driver**: `lib/waveshare_epd/epd7in5b_V2.py` is the only driver in `lib/waveshare_epd/` actually used; the directory ships drivers for other Waveshare models purely for reference. `.so` compiled binaries are gitignored (ARM-only, installed via apt on-device).

## 3. Module Layout

`app/main.py` was originally a single ~1600-line file (design.md §2 flagged this as expected to change once the file outgrew a single-file design). As of the v14 rewrite's Phase 1, it's split into focused modules — a pure relocation with no behavior change; every module below still does exactly what it did as part of the old monolith. Phase 2 adds the four-screen scheduler (`scheduler.py`), day-type resolution (`day_type.py`), and the boot connectivity checklist (`boot_checks.py`, `render/boot_screen.py`).

| Path | Role |
|---|---|
| `app/main.py` | Entry point / orchestration only: startup validation, hardware init, the boot screen, and the main scheduler/fetch/render loop. Imports everything else. |
| `app/config.py` | All environment variable loading and layout constants (`SCREEN_WIDTH`/`SCREEN_HEIGHT`/`COLUMN_OFFSET` and everything derived from them), `validate_configuration()`, the `refresh_requested` event, `boot_timestamp`. Every other module imports from here — the single source of truth for configuration. `DYNAMIC_CONFIG_VARS` + `reload_dynamic_vars()` + `config_reload_requested` support Phase 4's narrow no-restart reload (currently just `FORCE_SCREEN` — see §5). |
| `app/health.py` | `sd_notify()` (systemd readiness/watchdog pings — hang detection is systemd's `WatchdogSec`, not an in-process timer) and `SystemHealth` (API-call/display-update counters, periodic stats logging, `write_status_file()` health snapshot for the web panel). |
| `app/fetchers.py` | The shared `http_session` (retrying `requests.Session`), `DataCache`, `BackoffManager`, and every data-fetch function: `get_bus_arrival`, `get_train_disruptions`, `get_weather` (Home Assistant first, Open-Meteo fallback — see §4.2), `get_bus_stop_coordinates`, `get_day_type_sensors`, the OneMap/Google journey-time calculators, and `fetch_data_parallel()`. |
| `app/mqtt_client.py` | `MQTTClient` only — instantiated inside `main()`, not a module-level singleton (matches pre-split behavior). |
| `app/scheduler.py` | Pure schedule logic for the four-screen model: `load_schedule_config()` (the only file-I/O boundary, reads `schedule_config.json`), `validate_schedule()`, `default_schedule_from_env()` (migration fallback from `WAKE_HOUR`/`SLEEP_HOUR`), `detect_overlaps()`, `get_next_wake_time()`, `resolve_active_screen()` (fixed precedence: `sleep_screen` > `bus_train_screen` > `daytime_screen` > `ha_screen`, skipping any screen with `window["enabled"] is False`). Also `SCREEN_DISPLAY_NAMES` (screen_name → friendly web-UI label) and `DISABLEABLE_SCREENS` (currently just `("ha_screen",)` — the only screen the web UI lets the user fully switch off). |
| `app/day_type.py` | Pure day-type resolution: `resolve_day_type()`, `DayTypeCache` (date-keyed, resolves once per calendar day), `resolve_todays_day_type()`. |
| `app/boot_checks.py` | Boot-time connectivity probes (`check_network`, `check_internet`, `check_lta_api`, `check_home_assistant`), `run_all_checks()`, and the pure `format_checklist_lines()`. |
| `app/reload_watch.py` | Pure file-change detection (`get_mtime()`, `has_changed()`) — `main.py`'s mtime-poll backstop for the dynamic-reload feature (§5, §15 of design.md). |
| `app/render/common.py` | Shared rendering primitives: `MDI` icon glyph table, the `FONT_REGISTRY`/`resolve_font_pair()` display-font chooser plus font loaders (`get_font`/`get_font_bold`/`get_icon_font`), `DisplayManager`, `draw_mdi_icon`, `get_weather_icon`. |
| `app/render/bus_train.py` | The `bus_train_screen`: `draw_bus_section`, `draw_train_section`, `draw_weather_section_right`, `draw_timestamp`, `display_combined_view`. |
| `app/render/sleep_screen.py` | `display_sleep_screen()` — the true overnight screen: minimal, locally-PIL-drawn (`MDI.WEATHER_NIGHT` icon + "Next wake: HH:MM", no network fetch). Highest precedence of the four screens — the "ultimate override," never gated by day-type. This is a *new* Phase 2 file — not the same file as the pre-Phase-2 `sleep_screen.py`, which was renamed to `ha_screen.py` (below) before this file was (re)created. |
| `app/render/ha_screen.py` | `display_ha_screen()` — fetches and displays the external HA dashboard screenshot. Renamed from `sleep_screen.py`/`display_sleep_screen()` earlier in Phase 2; now the **lowest precedence** of the four screens, shown per its own `schedule_config.json` entry only when none of the other three claim that moment. |
| `app/render/daytime_screen.py` | The word-clock screen: pure `time_in_words()`/`build_daytime_model()` (main.py compares the model's `bucket` between ticks and redraws only when the quarter-hour or the weather changes) plus `display_daytime_screen()` (word clock + date + weather). Beats `ha_screen` on overlap and is the safe fallback when no window matches at all. |
| `app/render/boot_screen.py` | `display_boot_checklist()` — runs `boot_checks.run_all_checks()` and renders all results in a single draw+display() pass, replacing the old static "System Starting..." text. |
| `app/render/debug_screen.py` | `display_debug_screen()` — dev-only env-var dump shown at boot when `DEBUG_SKIP_TIME_CHECK=true`. |
| `app/web_config.py` | Standalone Flask app: routes only. Real signed `session`-based auth (`login_required` decorator, CSRF-protected state-changing POSTs), `validate_web_config()` startup guard (refuses to run with a placeholder secret key or unset password hash), `/schedule`+`/save_schedule` (edits `schedule_config.json`, surfaces `scheduler.detect_overlaps()` warnings), `/api/restart` (restarts `bus_display` via `systemctl`), `/api/refresh` (existing MQTT data-refresh trigger). Does not share process memory with `main.py`. |
| `app/web_config_schema.py` | `CONFIG_SCHEMA` — pure data, drives the `.env`-editing form. |
| `app/web_config_env.py` | Pure `.env` read/build-updates/atomic-write logic — no Flask, testable with plain dicts. |
| `app/web_config_schedule_forms.py` | Pure form-data ↔ schedule dict conversion + atomic JSON writer; delegates all validation to `scheduler.py`. |
| `app/secrets_vault.py` | Fernet encrypt/decrypt for password-type `.env` values, `enc:`-prefixed storage, key-file management (`app/.encryption_key`, gitignored). |
| `app/templates/`, `app/static/` | Jinja templates and CSS/JS for the web config panel, replacing the old inline `HTML_TEMPLATE` string. |
| `lib/waveshare_epd/` | Vendored Waveshare display drivers; only `epd7in5b_V2.py` + `epdconfig.py` are live. |
| `pic/` | Fonts loaded by PIL at runtime. |
| `systemd/bus_display.service` | Deployed unit file for the main process — `ExecStart` still points at `app/main.py`, unaffected by the module split since the entry point's path didn't change. |
| `systemd/web_config.service` | Deployed unit file for the web config panel — same conventions as `bus_display.service`. |
| `systemd/bus_display_restart.sudoers.example` | Documents (not auto-installs) the one-time passwordless-sudo entry `/api/restart` needs. |
| `tools/layout_editor.html` | Standalone HTML/JS tool (no build step) for visually mocking up and exporting the on-screen layout — not deployed to the Pi, dev-only. Still references the pre-rename `sleep_screen`/`display_sleep_screen()` naming (see `todo.md`). |
| `tests/` | Stdlib `unittest` tests: pure-logic modules (`scheduler.py`, `day_type.py`, `boot_checks.py`'s formatting function, `secrets_vault.py`, `web_config_env.py`, `web_config_schedule_forms.py`) plus Flask `test_client()`-based auth/session/CSRF tests for `web_config.py` — run via `python -m unittest discover -s tests`. |

## 4. Runtime Components

### 4.1 Singletons (module scope)
Instantiated once at import time and shared across the whole process (each still lives in the module identified in §3's table):

| Singleton | Type | Module | Role |
|---|---|---|---|
| `http_session` | `requests.Session` | `fetchers.py` | Shared HTTP client with urllib3-level retry (3x, 500/502/503/504, backoff 0.5) |
| `backoff_manager` | `BackoffManager` | `fetchers.py` | Per-API-key exponential backoff gate before attempting a live fetch |
| `system_health` | `SystemHealth` | `health.py` | Counters for API calls/errors, display updates, uptime; periodic log line every 10 loop iterations |
| `cache` | `DataCache` | `fetchers.py` | In-memory TTL cache for bus/train/weather/journey-time responses (process-lifetime only, no persistence) |
| `mqtt_client` | `MQTTClient` | `main.py` (class defined in `mqtt_client.py`) | Created inside `main()`; wraps paho-mqtt, runs its network loop on a background daemon thread |
| `refresh_requested` | `threading.Event` | `config.py` | Cross-thread signal: MQTT callback thread → main loop thread |
| `config_reload_requested` | `threading.Event` | `config.py` | Cross-thread signal (Phase 4): MQTT callback thread → main loop thread, triggers `reload_dynamic_vars()` and/or a schedule reload |
| `day_type_cache` | `DayTypeCache` | `day_type.py` | Date-keyed (not TTL) cache — resolves `school_day`/`work_day`/`off_day` once per calendar day, not on every loop iteration |

### 4.2 Data-fetch layer
- `get_bus_arrival()`, `get_train_disruptions()`, `get_weather()` — each follows the same pattern: check backoff → check cache → live HTTP fetch → update cache + reset backoff on success, or fall back to stale cache + record backoff failure on error. `get_weather()` additionally chains two sources behind that one cache/backoff: Home Assistant first (skipped when unconfigured), then Open-Meteo (free, no key, coordinates from `WEATHER_LAT`/`WEATHER_LON` or the bus stop itself) — a backoff failure is recorded only when both fail.
- `get_bus_stop_coordinates()` — success-only memoized lookup (coordinates are static, no TTL needed; failures aren't memoized) used to seed journey-time routing and, since v15, as the default location for the Open-Meteo weather fallback.
- `calculate_journey_time_onemap()` / `calculate_journey_time_google()` — provider-specific routing calls behind a common return shape (`{duration_mins, arrival_time}`), selected via `ROUTING_API_PROVIDER`.
- `calculate_journey_times_with_api()` — orchestrates the above per tracked bus service, with its own cache TTL.
- `fetch_data_parallel()` — the entry point called each loop iteration: runs bus/train/weather concurrently on a 3-worker `ThreadPoolExecutor`, then computes journey times serially afterward (depends on bus results). Returns a 4-tuple `(bus_info, train_info, weather_info, journey_times)`.

### 4.3 Rendering layer
- `DisplayManager` — owns the two PIL `Image` buffers (`black_image`, `red_image`) matching the e-ink panel's B/W/R model; `clear_images()` resets both to white and returns fresh `ImageDraw.Draw` handles, `display()` pushes both buffers to the physical panel via the Waveshare driver.
- Font helpers (`get_font`, `get_font_bold`, `get_icon_font`) — all `lru_cache`'d PIL `ImageFont` loaders. The regular/bold pair is resolved once at import from `FONT_REGISTRY[DISPLAY_FONT]` (unknown name or missing file falls back to Atkinson Regular); the icon font always renders glyphs from the Material Design Icons webfont as text.
- Section draw functions (`draw_bus_section`, `draw_train_section`, `draw_weather_section_right`, `draw_timestamp`, plus inline drawing in `display_combined_view`) — pure functions that take a `draw`/`draw_r` pair (black/red buffers) and data, and paint directly onto them. See [screen_layout.md](screen_layout.md) for exact coordinates/fonts per element.
- `display_combined_view()` — the `bus_train_screen` renderer: draws header, bus column, train column, weather, then calls `display_mgr.display()`.
- `display_debug_screen()`, `display_sleep_screen()`, `display_ha_screen()`, `display_daytime_screen()`, `display_boot_checklist()` — alternate full-screen renders (config dump; true overnight screen; HA dashboard screenshot; word clock + date + weather; boot connectivity checklist) used outside the normal `bus_train_screen` flow.

### 4.4 Control layer
- `scheduler.resolve_active_screen(schedule, day_type, now)` — pure function; returns which of the four screens (`sleep_screen`/`bus_train_screen`/`daytime_screen`/`ha_screen`) is active, applying the fixed precedence order, gating `bus_train_screen` on `day_type == 'school_day'`, and skipping a disabled `ha_screen` (a gap it would have claimed falls through to `daytime_screen`). Replaces the old `is_in_wake_window()`.
- `day_type.resolve_todays_day_type()` — resolves `school_day`/`work_day`/`off_day` once per calendar day via `day_type_cache`, falling back to yesterday's value (or `DAY_TYPE_FALLBACK`) if Home Assistant is unreachable.
- `main()` — startup validation → load schedule → hardware init → boot checklist → main loop: resolve day-type → resolve active screen → dispatch to the matching screen (see [design.md](design.md) for the full state machine). While `sleep_screen` or `ha_screen` is active, the loop skips `fetch_data_parallel()` entirely (no LTA/weather polling) and only redraws on screen-entry or manual refresh.
- `cleanup()` / `signal_handler()` — shutdown path: disconnect MQTT, close HTTP session, release GPIO, log final stats. Wired to `SIGINT`/`SIGTERM` and `atexit`.

### 4.5 MQTT integration
- `MQTTClient` wraps paho-mqtt. On construction (only if `MQTT_ENABLED`), connects and starts `client.loop_start()` on a background thread so MQTT never blocks the render loop.
- Subscribes to `MQTT_TOPIC_REFRESH`; a matching payload sets `refresh_requested`, consumed by the main loop on its next iteration.
- Subscribes to `MQTT_TOPIC_CONFIG_RELOAD` (Phase 4); any message sets `config_reload_requested`, triggering `config.reload_dynamic_vars()` and/or a schedule reload on the main loop's next iteration. `web_config.py` publishes to this topic automatically after a successful schedule save.
- Publishes to `MQTT_TOPIC_STATUS` (retained) at each lifecycle transition: `online` → `sleeping`/`awake` → `refreshing` → `idle` → `offline`.

## 5. Data Flow — One Loop Iteration

```
sd_notify('WATCHDOG=1')   (systemd hang detection — WatchdogSec in bus_display.service)
   │
   ▼
check refresh_requested (MQTT) ──► if set: cache.clear(), manual_refresh=True, wake panel if asleep
   │
   ▼
dynamic config reload check (Phase 4 — narrow allowlist, config.DYNAMIC_CONFIG_VARS):
   config_reload_requested (MQTT) OR .env/schedule_config.json mtime changed
   ──► config.reload_dynamic_vars() (refreshes FORCE_SCREEN) and/or reload the schedule
   │
   ▼
resolve_todays_day_type() (cheap — only hits HA on calendar-date rollover)
   │
   ▼
resolve_active_screen(schedule, day_type, now) ──► 'sleep_screen' | 'bus_train_screen' | 'daytime_screen' | 'ha_screen'
   │  (fixed precedence: sleep_screen > bus_train_screen[school_day-gated] > daytime_screen > ha_screen;
   │   any schedule overlap logs a warning once)
   ▼
┌─ sleep_screen (ultimate override) ───────────────────────────────────────┐
│ on entry or manual refresh: display_sleep_screen(next_wake_time), epd.sleep() │
│ fetch_data_parallel() is NOT called — no LTA/weather polling while active │
│ sleep(SLEEP_INTERVAL), continue                                          │
└───────────────────────────────────────────────────────────────────────┘
   │ (not sleep_screen)
   ▼
┌─ ha_screen (lowest precedence — only shows in an unclaimed gap) ─────────┐
│ on entry or manual refresh: display_ha_screen(), epd.sleep()             │
│ fetch_data_parallel() is NOT called — no LTA/weather polling while active │
│ sleep(SLEEP_INTERVAL), continue                                          │
└───────────────────────────────────────────────────────────────────────┘
   │ (not sleep_screen or ha_screen — wake panel if it was asleep)
   ▼
┌─ bus_train_screen ──────────────────┐   ┌─ daytime_screen ──────────────────┐
│ fetch_data_parallel(force_refresh=  │   │ get_weather() (cache-served most  │
│   manual_refresh)                    │   │   ticks) → build_daytime_model()  │
│ display_combined_view(...)           │   │ redraw only when the quarter-hour │
│ mqtt_client.publish_status("idle")   │   │ bucket / weather changes (4/hour, │
│                                      │   │ aligned :00/:15/:30/:45)          │
└──────────────────────────────────────┘   └────────────────────────────────────┘
   │
   ▼
every 10th bus_train_screen iteration: system_health.log_stats()
   │
   ▼
sleep(WAKE_INTERVAL) → loop
```

## 6. External Integration Surface

| System | Direction | Protocol | Notes |
|---|---|---|---|
| LTA DataMall (bus arrival) | Pi → LTA | HTTPS, `AccountKey` header | Every wake-cycle iteration, subject to cache/backoff |
| LTA DataMall (train alerts) | Pi → LTA | HTTPS, `AccountKey` header | Same |
| LTA DataMall (bus stop info) | Pi → LTA | HTTPS, `AccountKey` header | Only for journey-time origin coordinates, cached indefinitely |
| OneMap routing | Pi → OneMap | HTTPS, optional bearer token | Geocode + public-transport route, only if `ROUTING_API_PROVIDER=onemap` |
| Google Directions | Pi → Google | HTTPS, API key query param | Only if `ROUTING_API_PROVIDER=google` |
| Home Assistant (weather) | Pi → HA | HTTPS REST, bearer token | Reads a single weather entity's state/attributes |
| Home Assistant (day-type sensors) | Pi → HA | HTTPS REST, bearer token | Reads `binary_sensor.school_day`/`binary_sensor.workday_sensor`; only once per calendar day (`day_type.DayTypeCache`), not every loop iteration |
| Home Assistant (ha_screen dashboard) | Pi → HA (Puppeteer add-on) | HTTPS, query-param config | Returns a rendered image, not JSON; converted to grayscale and pushed straight to the black buffer. Only fetched on entry into `ha_screen` or a manual refresh — not polled every loop iteration |
| MQTT broker | Pi ↔ broker | MQTT (paho), optional auth | Bidirectional: subscribes for refresh commands, publishes status |
| Web config panel | Browser → Pi | HTTP, signed Flask `session` auth + CSRF | Local-network only, no TLS; edits `.env` and `schedule_config.json` directly on disk; can trigger a real `bus_display` restart via `sudo systemctl` (requires a one-time sudoers entry) |

## 7. Hardware Interface

- **Panel**: Waveshare 7.5" e-Paper B/W/R, driven via `epd7in5b_V2` over SPI, using `pigpio` as the GPIO backend (`pigpiod` must be running).
- **Two-buffer color model**: the panel accepts two 1-bit image buffers per refresh — one for black content, one for red — composited by the panel controller itself. There is no direct RGB framebuffer; every draw call targets one buffer or the other explicitly (see [design.md](design.md) §Two-Buffer Rendering Model).
- **No partial refresh** is currently used — `epd.display()` always does a full-panel update.

## 8. Related Documents

- [specifications.md](specifications.md) — features and functional requirements
- [design.md](design.md) — design rationale, patterns, and trade-offs
- [screen_layout.md](screen_layout.md) — pixel-level layout reference
