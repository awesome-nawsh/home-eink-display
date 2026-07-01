# Changelog - Bus Arrival Display

## [V14] - Rewrite in progress (branch `v14-rewrite`)

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
