# Specifications — home-eink-display

Functional and configuration reference for the current codebase (v13.0). This is a living document — update it whenever behavior in `app/main.py` or `app/web_config.py` changes.

---

## 1. Purpose

A Raspberry Pi Zero W drives a Waveshare 7.5" black/white/red e-ink display mounted in a picture frame. During the day it shows live Singapore bus arrival times and MRT (train) disruption alerts for a household getting kids to school. Outside those hours it switches to a screenshot of a Home Assistant dashboard (weather, calendar, etc.) so the display stays useful all day without needing bus data.

## 2. Core Features

| Feature | Description | Config |
|---|---|---|
| Bus arrival times | Live arrivals for a single bus stop, up to 3 next buses per service, from LTA DataMall | `BUS_STOP_CODE_A`, `A_HEADER` |
| Bus load indicator | Per-arrival crowding level (Seats/Standing/Limited) shown as an icon + fill bar | derived from LTA `Load` field |
| MRT/train disruptions | Current disruption alerts (line, direction, affected stations, free-text advisory) or an "all clear" state | `TRAIN_API_URL` |
| Journey time estimate | Optional: for specific tracked bus services, computes total time-to-destination (wait + transit) via a routing API | `SHOW_JOURNEY_TIME`, `BUS_SERVICES_TO_TRACK`, `JOURNEY_DESTINATION`, `ROUTING_API_PROVIDER` |
| Weather | Current conditions from a Home Assistant weather entity, falling back to Open-Meteo (free, no API key) when HA is unconfigured or unreachable — location from `WEATHER_LAT`/`WEATHER_LON`, else the bus stop's own coordinates. Air quality shown next to humidity: an HA AQI sensor pair first (value + optional category), else the NEA 24-hour PSI (worst of the five regional readings) | `HOME_ASSISTANT_WEATHER_ENTITY`, `WEATHER_LAT`, `WEATHER_LON`, `HOME_ASSISTANT_AQI_ENTITY`, `HOME_ASSISTANT_AQI_CATEGORY_ENTITY` |
| `sleep_screen` | The true overnight screen — minimal, locally-drawn (`MDI.WEATHER_NIGHT` icon + "Next wake: HH:MM"), no network fetch. Per its own schedule window (default ~21:00–06:00). **Highest precedence of all four screens — the "ultimate override,"** always wins on a schedule overlap, never gated by day-type. While active, bus/train/weather polling is suspended entirely | schedule entry in `schedule_config.json` |
| `ha_screen` dashboard | Per its own schedule window (default a one-hour evening slot), screenshots a full Home Assistant Lovelace dashboard (via a Puppeteer HA add-on) and displays it directly. **Lowest precedence of the four screens** — only shows in a genuine gap none of the other three claim. While active, bus/train/weather polling is suspended entirely (only re-fetches on entry or manual refresh). Can be switched off entirely from the Schedule page's "Enabled" checkbox — the only one of the four screens with an on/off toggle, since the other three are load-bearing (see §3.1) | `HOME_ASSISTANT_DASHBOARD_URL`, `HA_SCREEN_*` (legacy `SLEEP_SCREEN_*` names still read as fallbacks) |
| `daytime_screen` | Shown when `sleep_screen` isn't active and `bus_train_screen` isn't eligible/scheduled; beats `ha_screen` on overlap and is the safe fallback when no window matches at all. A word clock ("Quarter past two") + date + current weather, redrawn only on quarter-hour boundaries or a weather change (see §3.1) | schedule entry in `schedule_config.json` |
| Day-type resolution | Once per calendar day, resolves `school_day`/`work_day`/`off_day` from two Home Assistant binary sensors; gates whether `bus_train_screen` is eligible to show (`school_day` only — `work_day`/`off_day` currently fall back to `daytime_screen`, not yet distinguished from each other) | `HOME_ASSISTANT_SCHOOL_DAY_ENTITY`, `HOME_ASSISTANT_WORKDAY_ENTITY`, `DAY_TYPE_FALLBACK` |
| Boot connectivity checklist | At startup, checks network/internet/LTA API/Home Assistant reachability and displays all four results in one render pass before the loop starts | `BOOT_CHECK_TIMEOUT`, `INTERNET_CHECK_URL` |
| Screen override (testing) | Forces one of the four screens regardless of schedule/day-type, for verifying a screen renders correctly on real hardware without waiting for its window/day-type to occur naturally. Not meant to be left set in production. Reloadable live (Phase 4) — no restart needed to change or clear it | `FORCE_SCREEN` |
| Dynamic (no-restart) config reload | The schedule and `FORCE_SCREEN` (only) can be changed without restarting `bus_display` — an MQTT `config_reload` message (auto-published by the web UI on schedule save) or an `.env`/`schedule_config.json` file-change poll trigger a live reload. Everything else still needs the Phase 3 `/api/restart` | `MQTT_TOPIC_CONFIG_RELOAD` |
| MQTT remote refresh | Home Assistant (or anything else) can publish to a topic to force an immediate manual refresh, including waking the display early | `MQTT_ENABLED`, `MQTT_TOPIC_REFRESH` |
| MQTT status publishing | Publishes lifecycle status (`online`/`sleeping`/`awake`/`refreshing`/`idle`/`offline`) to a retained topic for HA to consume | `MQTT_TOPIC_STATUS` |
| Web config panel | Flask app (`app/web_config.py`, own systemd unit) to edit `.env` and the four-screen schedule from a browser without SSH. Real signed-session auth + CSRF protection; can trigger a genuine `bus_display` restart | `WEB_CONFIG_*`, `SECRETS_KEY_PATH` |
| Web config: schedule editing | `/schedule` page edits `schedule_config.json`'s four screen windows directly, surfacing `scheduler.detect_overlaps()` conflict warnings in the UI | schedule entry in `schedule_config.json` |
| Secrets at rest | Password-type `.env` fields are encrypted (`enc:` prefix) when saved through the web UI; `config.py` decrypts transparently on read. Protects a leaked/shared/committed `.env` in isolation, not a compromised device | `SECRETS_KEY_PATH` |
| Font chooser | Display typeface selected from a bundled registry (Atkinson weight pairings, Inter, IBM Plex Sans, Noto Sans); unknown names fall back to Atkinson Regular. Restart-required | `DISPLAY_FONT` |
| Debug screen | Full-screen dump of all resolved config values for troubleshooting, shown at boot for 5s | `DEBUG_SKIP_TIME_CHECK=true` |

## 3. Functional Requirements

### 3.1 Four-screen scheduler and day-type gating
- Four screens — `sleep_screen`, `bus_train_screen`, `daytime_screen`, `ha_screen` — each have their own daily `start`/`end` window, defined in `schedule_config.json` (falls back to a schedule derived from the legacy `WAKE_HOUR`/`SLEEP_HOUR` if that file is missing or invalid). Windows may overlap; a fixed precedence resolves conflicts: `sleep_screen` > `bus_train_screen` > `daytime_screen` > `ha_screen`. Overlaps are logged as warnings, not treated as configuration errors.
- `sleep_screen` is the "ultimate override" — the true overnight state (default ~21:00–06:00), never gated by day-type, and always wins over the other three regardless of their configured windows. `ha_screen` is the lowest precedence of the four — it only shows in a genuine gap none of the other three claim.
- `ha_screen` can be fully disabled via the Schedule page's "Enabled" checkbox (`scheduler.DISABLEABLE_SCREENS`) — its start/end window is kept in `schedule_config.json` (so re-enabling restores it) but treated as if it never matched any time of day; a gap it would have claimed falls through to `daytime_screen` instead. `sleep_screen`, `bus_train_screen`, and `daytime_screen` don't get this toggle — disabling any of them would break the "always something on screen" guarantee (`daytime_screen` in particular is `resolve_active_screen()`'s final fallback for any uncovered moment).
- `bus_train_screen` is additionally gated by day-type: only eligible when today resolves to `school_day` (via `binary_sensor.school_day`/`binary_sensor.workday_sensor`, resolved once per calendar day). On `work_day` or `off_day`, `daytime_screen` shows instead — these two day-types aren't yet distinguished from each other (see `todo.md`).
- Refresh cadence: the loop ticks every `WAKE_INTERVAL` seconds while `bus_train_screen`/`daytime_screen` is active (default 30s), every `SLEEP_INTERVAL` seconds while `sleep_screen`/`ha_screen` is active (default 300s). While either of those two low-power screens is active, the loop does not call `fetch_data_parallel()` at all — no LTA bus/train polling, no weather fetch — only re-displaying on schedule-entry or a manual refresh.
- `daytime_screen` redraw policy: although the loop ticks every `WAKE_INTERVAL`, the panel only redraws when the quarter-hour bucket or the displayed weather changes — 4 full refreshes/hour, aligned to :00/:15/:30/:45 (a full e-ink refresh is slow and flashes the whole panel). Each boundary redraw lands within one loop tick (≤ ~30s) of the actual quarter-hour; the word clock's granularity makes that lag invisible. Weather on this screen comes from `get_weather()` directly (single fetch, cache-served most ticks), not the full `fetch_data_parallel()`.
- `DEBUG_SKIP_TIME_CHECK=true` bypasses the scheduler entirely (always shows `bus_train_screen`) and shows the debug screen at boot instead of the connectivity checklist.

### 3.2 Data freshness & resilience
- Bus and train data are cached for 20s (hardcoded, `CACHE_DURATION`), weather for `WEATHER_CACHE_DURATION` (default 1800s), journey-time lookups for `JOURNEY_TIME_CACHE_DURATION` (default 1800s).
- On a failed live fetch, the last good cached value is served regardless of TTL rather than showing an error or blank section — the display should always show plausible data if it has ever successfully fetched it once.
- Per-endpoint exponential backoff (starting 60s, doubling, capped at 900s) prevents hammering a consistently-failing API. A manual refresh (MQTT-triggered) bypasses both the TTL cache and the backoff window to force a real attempt.
- All outbound HTTP requests go through a `requests.Session` configured to auto-retry on 500/502/503/504 (3 attempts, exponential backoff).

### 3.3 Manual refresh via MQTT
- Publishing any of `refresh|update|on|1|true` (case-insensitive) to `MQTT_TOPIC_REFRESH` sets a flag the main loop picks up on its next iteration: it clears the entire cache, forces a live fetch, and if the display is currently asleep, wakes the panel immediately to show the refreshed data.

### 3.4 Startup validation
- On launch, `validate_configuration()` checks required variables are present and internally consistent (e.g. `ROUTING_API_PROVIDER=google` requires `GOOGLE_MAPS_API_KEY`). Missing required config aborts startup with exit code 1; missing optional config logs a warning and the corresponding feature degrades gracefully (e.g. no HA token → weather section stays empty, not a crash).

### 3.5 Reliability / self-recovery
- Hang detection is systemd's watchdog: the unit runs with `Type=notify` + `WatchdogSec=900`, and the main loop pings `sd_notify('WATCHDOG=1')` every tick. If the pings stop (hung loop, wedged network/GPIO call), systemd kills and restarts the process — the app does not attempt in-process recovery.
- During an LTA API outage, bus/train sections keep showing last-known-good data for up to `STALE_DATA_MAX_AGE` (default 600s), then switch to an explicit "data unavailable" error for that section. A successful-but-empty API response (no buses running) is not an error and renders blank. Weather serves stale data indefinitely (it ages gracefully).
- The display process writes a per-tick health snapshot (uptime, active screen, day-type, MQTT state, API counters) to `STATUS_FILE_PATH` (default `/tmp/bus_display_status.json`); the web panel's status bar reads it via `/api/status`. That same endpoint also reports the web panel's own uptime (`web_config` key, computed directly from its own process start time — no file involved, since it's the process serving the request).
- `SIGINT`/`SIGTERM` and normal exit both run a cleanup path: disconnect MQTT, close the HTTP session, log final stats, and release GPIO pins via the Waveshare driver's `module_exit(cleanup=True)`.

## 4. Non-Functional Requirements

- **Hardware constraint**: must run continuously on a Raspberry Pi Zero W (single core, 512MB RAM) — no heavyweight dependencies, no local ML, minimal memory footprint (in-memory-only caching, no database).
- **Display constraint**: the physical e-ink panel is slow to refresh (multi-second full refresh) and only supports 3 colors (black/white/red) with no partial-refresh support currently used — every render is a full redraw of both image buffers.
- **Network constraint**: assumes an intermittent/imperfect home network; all external calls must degrade gracefully rather than crash the loop.
- **No persistent storage of secrets in git**: all credentials live in `.env` (gitignored); `.env.example` documents every variable without real values.

## 5. Configuration Reference

Full list of environment variables — see `.env.example` as the source of truth; grouped summary below.

| Group | Variables |
|---|---|
| LTA DataMall | `API_KEY`, `API_BUS_URL`, `API_TRAIN_URL`, `API_BUS_STOP_INFO_URL` |
| Bus stop identity | `A_HEADER`, `BUS_STOP_CODE_A` |
| Journey time (optional) | `SHOW_JOURNEY_TIME`, `BUS_SERVICES_TO_TRACK`, `JOURNEY_DESTINATION`, `JOURNEY_DESTINATION_SHORT`, `ROUTING_API_PROVIDER`, `ONEMAP_API_KEY`, `GOOGLE_MAPS_API_KEY`, `JOURNEY_TIME_CACHE_DURATION` |
| Schedule (legacy fallback) | `WAKE_HOUR`, `SLEEP_HOUR`, `WAKE_INTERVAL`, `SLEEP_INTERVAL`, `DEBUG_SKIP_TIME_CHECK` |
| Three-screen scheduler | `SCHEDULE_CONFIG_PATH` (see `schedule_config.json.example`) |
| Day-type resolution | `HOME_ASSISTANT_SCHOOL_DAY_ENTITY`, `HOME_ASSISTANT_WORKDAY_ENTITY`, `DAY_TYPE_FALLBACK` |
| Boot connectivity checklist | `BOOT_CHECK_TIMEOUT`, `INTERNET_CHECK_URL` |
| Screen override (testing) | `FORCE_SCREEN` |
| Home Assistant — weather | `HOME_ASSISTANT_API_URL`, `HOME_ASSISTANT_TOKEN`, `HOME_ASSISTANT_WEATHER_ENTITY`, `WEATHER_CACHE_DURATION` |
| Home Assistant — ha_screen | `HOME_ASSISTANT_DASHBOARD_URL` (falls back to legacy `HOME_ASSISTANT_SLEEP_URL`), `HA_SCREEN_DASHBOARD`, `HA_SCREEN_EINK_MODE`, `HA_SCREEN_ZOOM`, `HA_SCREEN_FORMAT`, `HA_SCREEN_WAIT`, `HA_SCREEN_THEME` (each falls back to its legacy `SLEEP_SCREEN_*` name) |
| MQTT | `MQTT_ENABLED`, `MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC_REFRESH`, `MQTT_TOPIC_STATUS`, `MQTT_TOPIC_CONFIG_RELOAD` |
| Web config panel | `WEB_CONFIG_PORT`, `WEB_CONFIG_HOST`, `WEB_CONFIG_USERNAME`, `WEB_CONFIG_PASSWORD_HASH`, `WEB_CONFIG_SECRET_KEY` (both of the latter two required — no insecure fallback) |
| Secrets at rest | `SECRETS_KEY_PATH` |
| Caching | `CACHE_DURATION` |
| Logging | `LOG_LEVEL` |

## 6. Known Limitations / Future Work

From `README.md`'s roadmap, still open:
- Multiple bus stops with tabs + button to switch
- Physical refresh/reboot button + LED
- Calendar events from HA (today's events) on the `bus_train_screen`
- Single bus stop only — `BUS_STOP_CODE_A` is the only stop supported; no multi-stop UI exists yet despite the "_A" suffix implying future stops B/C.
- No partial e-ink refresh — every update is a full redraw, which is slower and causes the visible full-screen flash typical of e-ink.

Added by Phase 2's design but explicitly deferred (see `todo.md` for the full list):
- `work_day` and `off_day` are both treated identically (fall back to `daytime_screen`) — no distinct content for each yet (the v15 word-clock daytime screen shows the same view for both).
- Each screen supports exactly one daily window — no multi-period-per-day schedules yet.

Added by Phase 3's design but explicitly deferred (see `todo.md`):
- Login rate-limiting/lockout on the web config panel — single-admin LAN app, low risk, conscious skip.

Added by Phase 4's design but explicitly deferred (see `todo.md`):
- Dynamic reload only covers the schedule and `FORCE_SCREEN` — everything else (API keys, MQTT settings, HA entity IDs, cache durations) still requires a restart. Expanding the allowlist would require converting more read sites to dotted `config.SOMEVAR` lookups; not done unless a specific variable is worth that cost.

## 7. Related Documents

- [architecture.md](architecture.md) — system components, control flow, external integrations
- [design.md](design.md) — design rationale and patterns
- [screen_layout.md](screen_layout.md) — exact pixel layout, fonts, and colors of the rendered display
- `tools/layout_editor.html` — interactive visual mockup tool for the display layout
