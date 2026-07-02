# Project To-Do

Running checklist of planned work, grouped by phase. Crossed off as it lands;
new items get added here (not just in commit messages) so this file stays the
single place to look for "what's planned but not done yet."

See `design.md` for the design rationale behind each phase.

## Phase 2 — Four-screen scheduler, day-type gating, boot checklist

### Config & schedule storage
- [x] `app/schedule_config.json.example` template + `schedule_config.json` (gitignored) loader
- [x] `app/scheduler.py`: `parse_hhmm`, `validate_schedule`, `default_schedule_from_env`,
      `load_schedule_config`, `detect_overlaps`, `get_next_wake_time`, `resolve_active_screen`
- [x] `config.py` additions: `HOME_ASSISTANT_SCHOOL_DAY_ENTITY`, `HOME_ASSISTANT_WORKDAY_ENTITY`,
      `DAY_TYPE_FALLBACK`, `SCHEDULE_CONFIG_PATH`, `BOOT_CHECK_TIMEOUT`, `INTERNET_CHECK_URL`,
      `HOME_ASSISTANT_DASHBOARD_URL` (with legacy `HOME_ASSISTANT_SLEEP_URL` fallback)
- [x] Keep `WAKE_HOUR`/`SLEEP_HOUR` as migration-fallback inputs to `default_schedule_from_env()`

### Day-type resolution
- [x] `fetchers.py`: `get_day_type_sensors()` (fetch-only, follows `get_weather_from_homeassistant` pattern)
- [x] `app/day_type.py`: `resolve_day_type()` (pure), `DayTypeCache` (date-keyed, once/day),
      `resolve_todays_day_type()`

### Screens
- [x] Rename `render/sleep_screen.py` → `render/ha_screen.py`, `display_sleep_screen` → `display_ha_screen`
      (same Puppeteer/HA-dashboard-screenshot behavior, now driven by its own schedule entry)
- [x] New `render/sleep_screen.py`: `display_sleep_screen()` — the true overnight screen, minimal
      local PIL draw (`MDI.WEATHER_NIGHT` icon + "Next wake: HH:MM"), no network fetch.
      Highest precedence of all four screens ("ultimate override"), never day-type-gated
- [x] New `render/daytime_screen.py`: `display_daytime_screen()` — placeholder, "Day time screen" centered
- [x] New `app/boot_checks.py`: `check_network`, `check_internet`, `check_lta_api`,
      `check_home_assistant`, `run_all_checks`, `format_checklist_lines`
- [x] New `render/boot_screen.py`: `display_boot_checklist()` — replaces static "System Starting..." text

### main.py wiring
- [x] Delete `is_in_wake_window()` — superseded by `resolve_active_screen()`
- [x] Load schedule at startup, log `detect_overlaps()` warnings once
- [x] Boot sequence uses `display_boot_checklist()` (still gated behind `DEBUG_SKIP_TIME_CHECK`)
- [x] Per-loop: resolve day-type (cheap, cached) → resolve active screen → dispatch
- [x] `sleep_screen`/`ha_screen` active: skip `fetch_data_parallel()` entirely (no LTA/weather polling),
      keep MQTT connected + subscribed to refresh topic only, manual refresh still forces redraw
- [x] `bus_train_screen` only eligible on `day_type == 'school_day'`
- [x] `FORCE_SCREEN` env var: bypasses schedule/day-type resolution to force one screen for
      real-hardware testing; invalid values logged and ignored, not meant for production use

### Testing
- [x] `tests/test_scheduler.py` — validation, overlap detection, precedence resolution (4-screen model),
      `get_next_wake_time`
- [x] `tests/test_day_type.py` — resolution table, date-rollover caching
- [x] `tests/test_boot_checks.py` — pure formatting only (network checks are integration-only, not unit-tested)
- [x] `python -m unittest discover -s tests` documented as the test-run command

### Preview tooling
- [x] `tools/preview_render.py --screen daytime`
- [x] `tools/preview_render.py --screen sleep`
- [x] `tools/preview_render.py --screen boot` (fixed fake check results, no network)

### Docs (every commit/merge keeps these current, not just ChangeLog/architecture)
- [x] `architecture.md` — module table + data-flow section
- [x] `specifications.md` — §3.1 schedule section, feature table, known limitations
- [x] `screen_layout.md` — boot screen + sleep_screen + ha_screen + daytime_screen rows
- [x] `design.md` — day-type caching + fixed-precedence-with-warnings rationale
- [x] `ChangeLog.md` — new Phase 2 entry under `[V14]`
- [x] `.env.example` — new vars, `WAKE_HOUR`/`SLEEP_HOUR` marked legacy-fallback

## Deferred to a later phase (explicitly out of scope for Phase 2)

- [ ] Richer `ha_screen` behavior (e.g. theme/config surfaced once `web_config.py` is rewritten)
- [x] Real content for `daytime_screen` — done in v15 (word clock + date + weather, quarter-hour redraws)
- [ ] Distinguish `work_day` vs `off_day` content/behavior (Phase 2 treats both as "not school_day";
      v15's word-clock daytime screen still shows the same view for both)
- [x] Surface schedule-conflict warnings in a web-config UI — done in Phase 3 (`/schedule` page)
- [ ] Multi-period-per-day schedules (Phase 2 supports exactly one start/end window per screen)
- [ ] `tools/layout_editor.html` — reflect the `sleep_screen`/`ha_screen`/`daytime_screen` rename/split
      (its "Sleep screen" tab currently means the old HA-dashboard behavior, now `ha_screen` —
      ambiguous now that a true `sleep_screen` also exists)

## Phase 3 — `web_config.py` rewrite: session auth, scheduler UI, `/api/restart`, secrets at rest

### Auth
- [x] Real signed Flask `session` (itsdangerous) replacing the forgeable `logged_in=true` cookie
- [x] Minimal `login_required` decorator; `/api/*` routes return 401 JSON, HTML routes redirect
- [x] Minimal hand-rolled CSRF token (session-stored, checked on state-changing POSTs) — no new dependency
- [x] `validate_web_config()` startup guard — hard-fails on unset/placeholder `WEB_CONFIG_SECRET_KEY`
      or unset `WEB_CONFIG_PASSWORD_HASH`, no more insecure fallback defaults

### Secrets at rest
- [x] `app/secrets_vault.py` — Fernet encrypt/decrypt (`cryptography` dependency), `enc:`-prefixed
      storage, plaintext passthrough for pre-existing values, `app/.encryption_key` (gitignored, 0o600)
- [x] `config.py` decrypts the 5 password-type vars transparently on read
- [x] Password fields never echo their value back into rendered HTML; blank submission = unchanged

### Scheduler UI
- [x] `GET /schedule` + `POST /save_schedule` — edits `schedule_config.json`'s 4 screen windows,
      reuses `scheduler.validate_schedule()`/`detect_overlaps()`, atomic write-then-rename
- [x] `CONFIG_SCHEMA` updated: fixed stale `http://` defaults, `HOME_ASSISTANT_DASHBOARD_URL` rename,
      new "Day-Type & Scheduler" category incl. `FORCE_SCREEN` as a dropdown, legacy fields relabeled

### `/api/restart`
- [x] New route, restarts `bus_display` via `systemctl` (kept alongside the existing MQTT-based
      `/api/refresh`, distinct purposes)
- [x] `systemd/bus_display_restart.sudoers.example` — documented, not auto-installed
- [x] `systemd/web_config.service` — new persistent unit for the panel itself

### Templates & structure
- [x] `app/templates/` (Jinja files) + `app/static/` (CSS/JS) replacing the inline `HTML_TEMPLATE` string
- [x] Split into `web_config_schema.py`/`web_config_env.py`/`web_config_schedule_forms.py`/`secrets_vault.py`

### Testing
- [x] `tests/test_secrets_vault.py`, `test_web_config_env.py`, `test_web_config_schedule_forms.py`
- [x] `tests/test_web_config_auth.py` — includes the actual regression test for the auth bug
      (forged `logged_in=true` cookie and wrong-secret-signed session both correctly denied)

### Explicitly deferred
- [ ] Login rate-limiting/lockout — single-admin LAN app, low risk, conscious skip

## Web UI follow-ups (post-Phase-3)

- [x] Sort/categorize the Settings page fields better — done in v15 (categories ordered by
      touch-frequency, collapsible `<details>` cards)
- [x] Move the LTA API URLs (`API_BUS_URL`, `API_TRAIN_URL`, `API_BUS_STOP_INFO_URL`) into an
      "Advanced" section — done in v15 (Advanced card, collapsed by default, also holds the
      boot-check knobs)
- [ ] Group configurations by integration, with enable/disable gating: everything
      Home Assistant-related in its own tab/section (API URL, token, weather/day-type/AQI
      entities, ha_screen, dashboard URL), same for MQTT — each with a master "enabled"
      toggle, and the section's fields greyed out (visible but not editable) until the
      integration is enabled. Would need per-category enable flags in `CONFIG_SCHEMA`
      plus a little template/JS to toggle the disabled state.

## Phase 4 — Dynamic (no-restart) config reload for the schedule and `FORCE_SCREEN`

- [x] `app/reload_watch.py`: pure `get_mtime()`/`has_changed()` file-change detection
- [x] `config.py`: `DYNAMIC_CONFIG_VARS`, `reload_dynamic_vars()`, `config_reload_requested`,
      `MQTT_TOPIC_CONFIG_RELOAD`, explicit `ENV_FILE_PATH` constant
- [x] `mqtt_client.py`: subscribes to `MQTT_TOPIC_CONFIG_RELOAD`
- [x] `main.py`: mtime-poll + MQTT-triggered reload dispatch each loop tick; `config.FORCE_SCREEN`
      read via dotted access (not a bare imported name) so it sees live updates
- [x] `web_config.py`: auto-publishes `config_reload` after a schedule save or a `FORCE_SCREEN`-only
      settings save; differentiated flash messages
- [x] `web_config_schema.py`/`_field_macros.html`: `FORCE_SCREEN` marked `dynamic`, "applies live" badge
- [x] `tests/test_reload_watch.py`, `tests/test_config_force_screen.py`

### Explicitly deferred
- [ ] Expanding `DYNAMIC_CONFIG_VARS` beyond `FORCE_SCREEN`/the schedule — would need more read
      sites converted to dotted `config.SOMEVAR` lookups; only worth it for a specific variable
      someone actually wants to change without a restart

## v14 review pass — consciously skipped cleanups

The post-Phase-4 code review fixed the bugs/stale-comments/efficiency items; these
dead-code removals were reviewed and deliberately left in place (low value, zero
runtime cost) — tracked here so they aren't re-flagged as new discoveries later:

- [ ] Unused layout constants in `config.py` (`TOP_MARGIN`, `BOTTOM_MARGIN`, `FONT_XLARGE`)
- [ ] Unused `import json` in `fetchers.py`
- [ ] Dead locals in `render/bus_train.py` (`final_bus_y`/`final_train_y`, the unused `x`
      parameter branch in `draw_timestamp`)
- [ ] ~22 unused MDI icon constants in `render/common.py` (kept as a glyph palette)
- [ ] Dead `.btn-danger` CSS rule in `app/static/style.css`
- [x] FORCE_SCREEN dropdown renders two empty-value options — fixed in v15

## Future features (not yet scheduled to a phase)

- [x] Weather fallback — done in v15: `get_weather()` chains Home Assistant → Open-Meteo
      (free/no-key, `WEATHER_LAT`/`WEATHER_LON` or the bus stop's coordinates) → stale cache.
- [ ] Full no-HA/no-MQTT operation: audit every HA/MQTT-dependent feature and make sure each
      has a public-web-API fallback (or degrades cleanly) when those integrations are disabled.
      Weather (Open-Meteo) and air quality (NEA PSI) already fall back; still HA-only today:
      day-type resolution (falls back to `DAY_TYPE_FALLBACK` — could use a public school-holiday/
      workday calendar instead), `ha_screen` (inherently HA, should just be skippable), and
      MQTT-triggered refresh/reload (mtime-poll backstop already covers reload; manual refresh
      has no non-MQTT path yet). Ties into the enable/disable gating item under Web UI follow-ups.
- [ ] Calendar integration: for users without Home Assistant, or who'd rather not route calendar
      data through it, add a direct calendar integration (subscribe to a calendar `.ics` URL/feed)
      as an alternative to (or in addition to) any future HA-based calendar display.

## Typography

- [x] Font chooser — done in v15: `DISPLAY_FONT` in `.env`/the web panel picks from
      `render/common.py`'s `FONT_REGISTRY`, with graceful fallback to Atkinson Regular.
- [x] Curate and bundle e-ink-friendly typefaces — done in v15: OFL statics of Inter,
      IBM Plex Sans, and Noto Sans bundled in `pic/<family>/` (each with its OFL.txt),
      plus Atkinson Medium/SemiBold weight pairings. Adding further families later is a
      one-line `FONT_REGISTRY` entry + font files + schema option.

## Architecture: modularize for easier extension (not yet scheduled to a phase)

The four screens and their config fields are currently hardcoded (main.py's screen dispatch is an
if/elif chain, `scheduler.SCREEN_NAMES` is a fixed 4-tuple, `CONFIG_SCHEMA` is one static dict).
That's been fine for four screens with known behavior, but the following would need it to become
more plugin-like/registry-based rather than hardcoded:

- [ ] A screen registry/interface (e.g. each screen module registers itself with a name, a render
      function, and its own config fields) so adding a new screen — or a new config section — doesn't
      require touching `main.py`'s dispatch, `scheduler.py`'s `SCREEN_NAMES`, and `CONFIG_SCHEMA` all
      by hand in three places.
- [ ] A "rolling"/rotating screen type: cycles through multiple sub-views on a timer within its own
      schedule window (distinct from today's one-view-per-screen model).
- [ ] A custom image-slideshow screen: let the user point at a local folder (or a set of URLs) of
      images to cycle through, instead of (or alongside) the built-in screens.
- [ ] Support more than one `ha_screen` target: let the user configure a set of HA dashboard
      URLs to rotate through or pick from, instead of the single `HOME_ASSISTANT_DASHBOARD_URL`
      today.
