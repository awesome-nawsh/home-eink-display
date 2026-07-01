# Changelog - Bus Arrival Display

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
