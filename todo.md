# Project To-Do

Running checklist of planned work, grouped by phase. Crossed off as it lands;
new items get added here (not just in commit messages) so this file stays the
single place to look for "what's planned but not done yet."

See `/Users/seanjmiller/.claude/plans/twinkly-wishing-platypus.md` (Claude
Code plan file) for the full design rationale behind each phase.

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
- [ ] Real content for `daytime_screen` (currently a placeholder)
- [ ] Distinguish `work_day` vs `off_day` content/behavior (Phase 2 treats both as "not school_day")
- [ ] Surface schedule-conflict warnings in a web-config UI (needs the Phase 3 `web_config.py` rewrite)
- [ ] Multi-period-per-day schedules (Phase 2 supports exactly one start/end window per screen)
- [ ] `tools/layout_editor.html` — reflect the `sleep_screen`/`ha_screen`/`daytime_screen` rename/split
      (its "Sleep screen" tab currently means the old HA-dashboard behavior, now `ha_screen` —
      ambiguous now that a true `sleep_screen` also exists)

## Phase 3 (not started)

- [ ] `web_config.py` rewrite: session-based auth, secret/password startup guards, Jinja templates,
      scheduler UI (including conflict-warning display), `/api/restart`

## Phase 4 (not started)

- [ ] Dynamic (no-restart) config reload: `Config.reload()`, restart-required vs. dynamic
      classification per variable, MQTT `config_reload` topic + mtime-poll backstop
