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

`app/main.py` is a single long-running process, started and supervised by systemd. It's the entry point for one process that owns the render loop, all API calls, MQTT, and direct hardware access to the e-ink panel via `lib/waveshare_epd/epd7in5b_V2.py` — as of the v14 module split, `main.py` itself is thin orchestration only, importing config/fetching/rendering logic from sibling modules (§3). `app/web_config.py` is a separate, optional Flask process — it only reads/writes the `.env` file and can trigger a restart of the main service; it holds no runtime state of its own and does not talk to the display directly.

## 2. Process & Deployment Topology

- **Runtime**: single Python 3 process per service, no containers, no supervisor besides systemd.
- **`bus_display.service`** (deployed to `/etc/systemd/system/`): runs `app/main.py` as user `seanj`, group `gpio`, with `SupplementaryGroups=gpio spi i2c` for hardware access. `Restart=on-failure`, `RestartSec=10` — this is the app's *only* self-healing mechanism (see [design.md](design.md) §Watchdog).
- **`web_config.py`** is not managed by the shipped systemd unit — it must be run manually or added as a second unit if the web config panel is wanted persistently (noted in `CLAUDE.md`).
- **Dependencies**: Python packages via `pip` (`requirements.txt`); `pigpio`/`pigpiod` installed via `apt` (not pip-installable on Pi in a usable form) and must be running (`bus_display.service` has `Wants=pigpiod.service`, `After=pigpiod.service`).
- **Fonts**: loaded at runtime from `pic/` (Atkinson Hyperlegible Next `.otf`, Material Design Icons `.ttf`) via absolute paths resolved from the script's own directory.
- **Driver**: `lib/waveshare_epd/epd7in5b_V2.py` is the only driver in `lib/waveshare_epd/` actually used; the directory ships drivers for other Waveshare models purely for reference. `.so` compiled binaries are gitignored (ARM-only, installed via apt on-device).

## 3. Module Layout

`app/main.py` was originally a single ~1600-line file (design.md §2 flagged this as expected to change once the file outgrew a single-file design). As of the v14 rewrite's Phase 1, it's split into focused modules — a pure relocation with no behavior change; every module below still does exactly what it did as part of the old monolith.

| Path | Role |
|---|---|
| `app/main.py` | Entry point / orchestration only: startup validation, hardware init, the boot screen, and the main wake/sleep/fetch/render loop. Imports everything else. |
| `app/config.py` | All environment variable loading and layout constants (`SCREEN_WIDTH`/`SCREEN_HEIGHT`/`COLUMN_OFFSET` and everything derived from them), `validate_configuration()`, the `refresh_requested` event, `boot_timestamp`. Every other module imports from here — the single source of truth for configuration. |
| `app/health.py` | `Watchdog` (stuck-loop detection) and `SystemHealth` (API-call/display-update counters, periodic stats logging), plus their module-level singleton instances. |
| `app/fetchers.py` | The shared `http_session` (retrying `requests.Session`), `DataCache`, `BackoffManager`, and every data-fetch function: `get_bus_arrival`, `get_train_disruptions`, `get_weather_from_homeassistant`, `get_bus_stop_coordinates`, the OneMap/Google journey-time calculators, and `fetch_data_parallel()`. |
| `app/mqtt_client.py` | `MQTTClient` only — instantiated inside `main()`, not a module-level singleton (matches pre-split behavior). |
| `app/render/common.py` | Shared rendering primitives: `MDI` icon glyph table, font loaders (`get_font`/`get_font_bold`/`get_icon_font`), `DisplayManager`, `draw_mdi_icon`, `get_weather_icon`. |
| `app/render/bus_train.py` | The "awake" screen: `draw_bus_section`, `draw_train_section`, `draw_weather_section_right`, `draw_timestamp`, `display_combined_view`. |
| `app/render/sleep_screen.py` | `display_sleep_screen()` — fetches and displays the external HA dashboard screenshot outside the wake window. Named `sleep_screen` (not yet `daytime`) deliberately — that rename is a later-phase concept change, not part of the Phase 1 relocation. |
| `app/render/debug_screen.py` | `display_debug_screen()` — dev-only env-var dump shown at boot when `DEBUG_SKIP_TIME_CHECK=true`. |
| `app/web_config.py` | Standalone Flask app to edit `.env` from a browser (`CONFIG_SCHEMA` dict drives an auto-generated form; reads `SystemHealth`-shaped status conceptually but does not share process memory with `main.py`). Untouched by the Phase 1 module split. |
| `lib/waveshare_epd/` | Vendored Waveshare display drivers; only `epd7in5b_V2.py` + `epdconfig.py` are live. |
| `pic/` | Fonts loaded by PIL at runtime. |
| `systemd/bus_display.service` | Deployed unit file for the main process — `ExecStart` still points at `app/main.py`, unaffected by the module split since the entry point's path didn't change. |
| `tools/layout_editor.html` | Standalone HTML/JS tool (no build step) for visually mocking up and exporting the on-screen layout — not deployed to the Pi, dev-only. |

## 4. Runtime Components

### 4.1 Singletons (module scope)
Instantiated once at import time and shared across the whole process (each still lives in the module identified in §3's table):

| Singleton | Type | Module | Role |
|---|---|---|---|
| `http_session` | `requests.Session` | `fetchers.py` | Shared HTTP client with urllib3-level retry (3x, 500/502/503/504, backoff 0.5) |
| `watchdog` | `Watchdog` | `health.py` | Detects a hung main loop (300s without a `feed()`) |
| `backoff_manager` | `BackoffManager` | `fetchers.py` | Per-API-key exponential backoff gate before attempting a live fetch |
| `system_health` | `SystemHealth` | `health.py` | Counters for API calls/errors, display updates, uptime; periodic log line every 10 loop iterations |
| `cache` | `DataCache` | `fetchers.py` | In-memory TTL cache for bus/train/weather/journey-time responses (process-lifetime only, no persistence) |
| `mqtt_client` | `MQTTClient` | `main.py` (class defined in `mqtt_client.py`) | Created inside `main()`; wraps paho-mqtt, runs its network loop on a background daemon thread |
| `refresh_requested` | `threading.Event` | `config.py` | Cross-thread signal: MQTT callback thread → main loop thread |

### 4.2 Data-fetch layer
- `get_bus_arrival()`, `get_train_disruptions()`, `get_weather_from_homeassistant()` — each follows the same pattern: check backoff → check cache → live HTTP fetch → update cache + reset backoff on success, or fall back to stale cache + record backoff failure on error.
- `get_bus_stop_coordinates()` — `lru_cache`'d lookup (coordinates are static, no TTL needed) used only to seed journey-time routing.
- `calculate_journey_time_onemap()` / `calculate_journey_time_google()` — provider-specific routing calls behind a common return shape (`{duration_mins, arrival_time}`), selected via `ROUTING_API_PROVIDER`.
- `calculate_journey_times_with_api()` — orchestrates the above per tracked bus service, with its own cache TTL.
- `fetch_data_parallel()` — the entry point called each loop iteration: runs bus/train/weather concurrently on a 3-worker `ThreadPoolExecutor`, then computes journey times serially afterward (depends on bus results). Returns a 4-tuple `(bus_info, train_info, weather_info, journey_times)`.

### 4.3 Rendering layer
- `DisplayManager` — owns the two PIL `Image` buffers (`black_image`, `red_image`) matching the e-ink panel's B/W/R model; `clear_images()` resets both to white and returns fresh `ImageDraw.Draw` handles, `display()` pushes both buffers to the physical panel via the Waveshare driver.
- Font helpers (`get_font`, `get_font_bold`, `get_icon_font`) — all `lru_cache`'d PIL `ImageFont` loaders; icon font renders individual glyphs from the Material Design Icons webfont as text.
- Section draw functions (`draw_bus_section`, `draw_train_section`, `draw_weather_section_right`, `draw_timestamp`, plus inline drawing in `display_combined_view`) — pure functions that take a `draw`/`draw_r` pair (black/red buffers) and data, and paint directly onto them. See [screen_layout.md](screen_layout.md) for exact coordinates/fonts per element.
- `display_combined_view()` — the main "awake" screen: draws header, bus column, train column, weather, then calls `display_mgr.display()`.
- `display_debug_screen()`, `display_sleep_screen()` — alternate full-screen renders (config dump; HA dashboard screenshot respectively) used outside the normal awake flow.

### 4.4 Control layer
- `is_in_wake_window()` — pure function, handles overnight wrap-around wake/sleep windows.
- `main()` — startup validation → hardware init → boot screen → `while True` loop (see [design.md](design.md) for the full state machine).
- `cleanup()` / `signal_handler()` — shutdown path: disconnect MQTT, close HTTP session, release GPIO, log final stats. Wired to `SIGINT`/`SIGTERM` and `atexit`.

### 4.5 MQTT integration
- `MQTTClient` wraps paho-mqtt. On construction (only if `MQTT_ENABLED`), connects and starts `client.loop_start()` on a background thread so MQTT never blocks the render loop.
- Subscribes to `MQTT_TOPIC_REFRESH`; a matching payload sets `refresh_requested`, consumed by the main loop on its next iteration.
- Publishes to `MQTT_TOPIC_STATUS` (retained) at each lifecycle transition: `online` → `sleeping`/`awake` → `refreshing` → `idle` → `offline`.

## 5. Data Flow — One Wake-Cycle Iteration

```
watchdog.feed()
   │
   ▼
check refresh_requested (MQTT) ──► if set: cache.clear(), manual_refresh=True, wake panel if sleeping
   │
   ▼
is_in_wake_window()? ──► No: publish "sleeping" (once), try display_sleep_screen(), epd.sleep(), sleep(SLEEP_INTERVAL), continue
   │ Yes
   ▼
fetch_data_parallel(force_refresh=manual_refresh)
   │  (bus, train, weather fetched concurrently; journey times computed after)
   ▼
display_combined_view(bus_info, train_info, weather_info, journey_times, manual_refresh, mqtt_connected)
   │  (full redraw of both image buffers, pushed to physical panel)
   ▼
mqtt_client.publish_status("idle")
   │
   ▼
every 10th iteration: system_health.log_stats()
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
| Home Assistant (sleep screenshot) | Pi → HA (Puppeteer add-on) | HTTPS, query-param config | Returns a rendered image, not JSON; converted to grayscale and pushed straight to the black buffer |
| MQTT broker | Pi ↔ broker | MQTT (paho), optional auth | Bidirectional: subscribes for refresh commands, publishes status |
| Web config panel | Browser → Pi | HTTP, Flask session auth | Local-network only by default; edits `.env` directly on disk |

## 7. Hardware Interface

- **Panel**: Waveshare 7.5" e-Paper B/W/R, driven via `epd7in5b_V2` over SPI, using `pigpio` as the GPIO backend (`pigpiod` must be running).
- **Two-buffer color model**: the panel accepts two 1-bit image buffers per refresh — one for black content, one for red — composited by the panel controller itself. There is no direct RGB framebuffer; every draw call targets one buffer or the other explicitly (see [design.md](design.md) §Two-Buffer Rendering Model).
- **No partial refresh** is currently used — `epd.display()` always does a full-panel update.

## 8. Related Documents

- [specifications.md](specifications.md) — features and functional requirements
- [design.md](design.md) — design rationale, patterns, and trade-offs
- [screen_layout.md](screen_layout.md) — pixel-level layout reference
