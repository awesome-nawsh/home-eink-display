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
| Weather | Current conditions pulled from a Home Assistant weather entity | `HOME_ASSISTANT_WEATHER_ENTITY` |
| Sleep-screen dashboard | Outside the wake window, screenshots a full Home Assistant Lovelace dashboard (via a Puppeteer HA add-on) and displays it directly | `SLEEP_SCREEN_DASHBOARD`, `SLEEP_SCREEN_*` |
| MQTT remote refresh | Home Assistant (or anything else) can publish to a topic to force an immediate manual refresh, including waking the display early | `MQTT_ENABLED`, `MQTT_TOPIC_REFRESH` |
| MQTT status publishing | Publishes lifecycle status (`online`/`sleeping`/`awake`/`refreshing`/`idle`/`offline`) to a retained topic for HA to consume | `MQTT_TOPIC_STATUS` |
| Web config panel | Optional Flask app (`app/web_config.py`, not run by the main systemd service) to edit `.env` from a browser without SSH | `WEB_CONFIG_*` |
| Debug screen | Full-screen dump of all resolved config values for troubleshooting, shown at boot for 5s | `DEBUG_SKIP_TIME_CHECK=true` |

## 3. Functional Requirements

### 3.1 Wake/sleep schedule
- The display is "awake" (showing bus/train data) between `WAKE_HOUR` and `SLEEP_HOUR` (24h, both configurable; supports overnight wrap where `WAKE_HOUR > SLEEP_HOUR`).
- Refresh cadence: every `WAKE_INTERVAL` seconds while awake (default 30s), every `SLEEP_INTERVAL` seconds while asleep (default 300s) — while asleep, the loop only re-checks the sleep-screen image, it does not fetch bus/train data.
- `DEBUG_SKIP_TIME_CHECK=true` bypasses the schedule entirely (always awake) and shows the debug screen at boot instead of the boot banner.

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
- A watchdog requires the main loop to "feed" it at least once every 300s; if it doesn't, the process exits cleanly (does not hang). Recovery relies on systemd's `Restart=on-failure` to relaunch the process — the app does not attempt in-process recovery.
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
| Schedule | `WAKE_HOUR`, `SLEEP_HOUR`, `WAKE_INTERVAL`, `SLEEP_INTERVAL`, `DEBUG_SKIP_TIME_CHECK` |
| Home Assistant — weather | `HOME_ASSISTANT_API_URL`, `HOME_ASSISTANT_TOKEN`, `HOME_ASSISTANT_WEATHER_ENTITY`, `WEATHER_CACHE_DURATION` |
| Home Assistant — sleep screen | `HOME_ASSISTANT_SLEEP_URL`, `SLEEP_SCREEN_DASHBOARD`, `SLEEP_SCREEN_EINK_MODE`, `SLEEP_SCREEN_ZOOM`, `SLEEP_SCREEN_FORMAT`, `SLEEP_SCREEN_WAIT`, `SLEEP_SCREEN_THEME` |
| MQTT | `MQTT_ENABLED`, `MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC_REFRESH`, `MQTT_TOPIC_STATUS` |
| Web config panel | `WEB_CONFIG_PORT`, `WEB_CONFIG_HOST`, `WEB_CONFIG_USERNAME`, `WEB_CONFIG_PASSWORD_HASH`, `WEB_CONFIG_SECRET_KEY` |
| Caching | `CACHE_DURATION` |
| Logging | `LOG_LEVEL` |

## 6. Known Limitations / Future Work

From `README.md`'s roadmap, still open:
- Multiple bus stops with tabs + button to switch
- Physical refresh/reboot button + LED
- Air quality data next to weather
- Calendar events from HA (today's events) on the awake screen
- Single bus stop only — `BUS_STOP_CODE_A` is the only stop supported; no multi-stop UI exists yet despite the "_A" suffix implying future stops B/C.
- No partial e-ink refresh — every update is a full redraw, which is slower and causes the visible full-screen flash typical of e-ink.

## 7. Related Documents

- [architecture.md](architecture.md) — system components, control flow, external integrations
- [design.md](design.md) — design rationale and patterns
- [screen_layout.md](screen_layout.md) — exact pixel layout, fonts, and colors of the rendered display
- `tools/layout_editor.html` — interactive visual mockup tool for the display layout
