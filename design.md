# Design — home-eink-display

Design rationale: why the codebase is shaped the way it is, and the trade-offs behind each major decision. Read alongside [architecture.md](architecture.md) (the resulting structure) and [specifications.md](specifications.md) (the behavior it produces).

---

## 1. Guiding constraints

Every design decision in this codebase traces back to three hard constraints:

1. **A Raspberry Pi Zero W is weak** — single core, 512MB RAM. This rules out heavyweight frameworks, background job queues, databases, or anything that assumes headroom.
2. **The e-ink panel is slow and 3-color only** — full refreshes take seconds and visibly flash; there's no RGB, only black/white/red. This shapes both the rendering model and the refresh cadence (30s awake / 300s asleep, not real-time).
3. **This is a hobby project run unattended in someone's hallway** — it needs to keep working for weeks without intervention, degrade gracefully when an API is flaky, and be recoverable by "just restart the service" rather than requiring manual debugging. Simplicity and resilience were prioritized over architectural purity.

## 2. Monolithic single-file design (`main.py`)

**Decision**: nearly all logic — config, HTTP clients, caching, rendering, MQTT, the main loop — lives in one ~1580-line file rather than being split into modules/packages.

**Why**: on a Pi Zero W, process startup and import overhead matter, and there's exactly one entry point with no code reuse across other programs (aside from `web_config.py`, which is deliberately a separate, independent process). A single file also means no ambiguity about import order for the `sys.path` manipulation needed to reach the vendored `lib/waveshare_epd/` driver. The trade-off — a large file that's harder to navigate — is mitigated by consistent section grouping (constants → classes → fetchers → draw functions → main loop) and by this documentation set.

**When to reconsider**: if the file keeps growing (e.g. multi-bus-stop support, more integrations), splitting into `fetchers.py` / `render.py` / `mqtt.py` modules imported by `main.py` would be the natural next step — but only once there's enough surface area to justify the added import complexity.

## 3. Two-buffer rendering model

**Decision**: every draw function takes a `(draw, draw_r)` pair — two separate `PIL.ImageDraw.Draw` handles, one for the black image buffer, one for the red image buffer — rather than a single RGB canvas that gets quantized down to 3 colors at the end.

**Why**: this mirrors exactly how the Waveshare panel's controller works — it physically wants two 1-bit buffers, not one 24-bit image. Drawing directly into the two buffers avoids a color-quantization step and guarantees pixel-perfect output (no dithering artifacts, no ambiguity about which shade of a color the panel will render). The cost is that every draw call site has to know, explicitly, which buffer to target — there's no "just draw a red rectangle" abstraction. This is why [screen_layout.md](screen_layout.md) tracks color per element: it's not a style choice, it's a choice of *which physical buffer* the pixels land in.

**Implication for future layout changes**: any new element must be assigned to exactly one buffer (black or red) at design time — the panel doesn't support blending or a third mixed color.

## 4. Caching and backoff as two separate mechanisms

**Decision**: `DataCache` (TTL-based, "don't refetch if data is still fresh") and `BackoffManager` (failure-based, "don't retry if the endpoint is currently unhealthy") are deliberately kept as two independent, composable mechanisms rather than one combined "smart fetch" abstraction.

**Why**: they answer different questions and fail differently. Cache TTL protects the upstream API (and the Pi's limited bandwidth/CPU) from unnecessary polling under normal conditions. Backoff protects against wasting a refresh cycle retrying an API that's *currently down* — without it, every 20-30s loop iteration would re-attempt a failing call and add latency/log noise. Keeping them separate means each has a single, simple responsibility (`should_retry(key)` / `get(key, duration)`), and either can be reasoned about or changed independently. A manual (MQTT-triggered) refresh deliberately bypasses *both* — the user asked for fresh data now, so both the "don't bother yet" (cache) and "don't retry yet" (backoff) rationales are overridden.

**Trade-off accepted**: stale-cache fallback means the display can silently show data that's minutes old during an outage, with only a debug-level log line noting it. This was a deliberate choice — for a hallway display, "slightly stale bus times" is far less disruptive than "blank section" or a crash, and there was no requirement to surface staleness visually. If that trade-off changes (e.g. a future request to show a "data may be stale" indicator), that's a `screen_layout.md`-level addition, not a caching-layer change.

## 5. Stale-cache-first error handling philosophy

**Decision**: fetchers never propagate exceptions up to the render layer. Every failure path returns *something renderable* — the last good cached value, or an empty/sentinel value (e.g. `[]` for no cached bus data) — never `None` propagating into a draw function that assumes a dict.

**Why**: a crashed render loop means a frozen display until systemd notices and restarts the process (and even then, the panel would need a fresh full render). Given the panel's slow refresh and the "just works in a hallway" requirement, availability of *some* output beats correctness of *fresh* output. This is the same philosophy behind the watchdog (§7) — the system is designed to degrade and keep going, not to halt on the first sign of trouble.

## 6. Provider-agnostic routing abstraction

**Decision**: `calculate_journey_time_onemap()` and `calculate_journey_time_google()` are separate functions with completely different request/response handling, but both normalize to the same `{'duration_mins', 'arrival_time'}` shape, and `calculate_journey_times_with_api()` dispatches between them via a single `ROUTING_API_PROVIDER` env var.

**Why**: OneMap is free and Singapore-specific (good default, no API key friction) but Google Maps may give better transit routing quality in edge cases and is worth supporting as a drop-in swap. Normalizing the return shape means `draw_bus_section()` and the caching layer above it don't need to know or care which provider answered — the abstraction boundary sits exactly at "provider-specific request/response parsing" and nowhere else. This avoids over-engineering a generic "routing provider interface" class hierarchy for what is, in practice, exactly two providers with no plans for more.

## 7. Reliability model: watchdog + systemd, not in-process self-healing

**Decision**: `Watchdog.check()` only *detects* a stuck loop (no `feed()` in 300s) and causes the process to exit cleanly. It does **not** attempt to reset internal state, restart threads, or recover in-process. Recovery is delegated entirely to systemd's `Restart=on-failure`.

**Why**: attempting in-process recovery from an unknown-cause hang (e.g. a wedged GPIO call, a thread deadlock) is unreliable — you can't safely "reset" state you don't understand the corruption of. Exiting cleanly and letting the OS supervisor restart the whole process guarantees a known-good state (all singletons freshly constructed, all threads freshly started, GPIO cleanly reinitialized). This is a deliberate "let it crash" philosophy, borrowed from supervisor-tree designs, chosen because it's simple to reason about and matches what a solo hobbyist can debug via `journalctl` rather than in-process diagnostics.

**Known gap**: the CLAUDE.md "Known Issues" note about a `Restart=alwayson-falure` typo (now fixed to `Restart=on-failure`) is exactly the failure mode this model is vulnerable to — if the systemd unit's restart policy is ever misconfigured, the watchdog's clean exit becomes a permanent outage instead of a recovery. The correctness of this entire reliability model depends on the deployed unit file matching the one in `systemd/bus_display.service`.

This model previously had a second, code-level version of the same gap: `main()`'s `finally` block used to unconditionally `return 0`, and the watchdog-triggered exit path fell through to an implicit `None` return with no explicit exit code — both of which produced exit code `0` (success) regardless of *why* the process was exiting. Since `Restart=on-failure` only restarts on a non-zero exit, this meant a fatal error or a watchdog-detected hang would exit "successfully" and never trigger a restart at all — the process would just silently stay dead. Fixed by removing the `finally`-block `return 0` (so the `try`/`except` return values propagate) and making the watchdog path `return 1` explicitly instead of `break`ing into the same swallowed-exit-code trap.

## 8. MQTT as a non-blocking side channel

**Decision**: `MQTTClient` runs its network loop (`client.loop_start()`) on its own background thread, communicating with the main render loop only through a single `threading.Event` (`refresh_requested`) and one-way status publishes. It's constructed to no-op entirely if `MQTT_ENABLED=false`.

**Why**: the render loop's timing (30s/300s cadence, plus the multi-second e-ink refresh itself) must never be blocked by network I/O to a broker that might be slow, unreachable, or misconfigured. A single `Event` is the minimal-surface-area primitive for "signal that something happened" across threads — no queue, no lock contention beyond what `threading.Event` already provides internally. Making MQTT fully optional (rather than a required integration) matches this project's audience: someone running a bare Pi with no MQTT broker should get full core functionality (bus/train/weather) with zero configuration burden.

## 9. Config-as-environment, validated once at startup

**Decision**: all configuration is read from `.env` via `python-dotenv` at import time into module-level constants (not passed as parameters, not re-read at runtime), with a single `validate_configuration()` gate at startup that can hard-fail the process before any hardware or network I/O happens.

**Why**: fail-fast at startup is far cheaper to debug than failing three hours into unattended operation because a required key was missing. Treating config as static for the process lifetime (no hot-reload) is intentional — the systemd `Restart=on-failure` policy already means "change `.env`, restart the service" is the supported workflow (this is exactly what the web config panel's `/api/refresh` restart trigger assumes). Runtime hot-reloading of config was considered unnecessary complexity for a single-operator hobby deployment.

## 10. Font and icon strategy

**Decision**: text uses a single accessible font family (Atkinson Hyperlegible Next, Regular + Bold only) at a small fixed set of sizes; icons are drawn as glyphs from a bundled Material Design Icons webfont via the same PIL text-drawing path, not as separate bitmap/vector image assets.

**Why**: Atkinson Hyperlegible Next was chosen specifically for legibility at e-ink's screen-door-effect resolution and viewing distance across a hallway — this was a deliberate accessibility choice (see README credits), not a default. Drawing icons as font glyphs (rather than loading and blitting bitmap icons) keeps the rendering code uniform — every visual element on screen goes through the same `draw.text()`-shaped code path with a font object and a fill color, which is simpler to reason about and cheaper on a Pi Zero than image compositing. The cost is a fixed icon set (whatever MDI v7.4.47 ships) and coarser control over icon appearance than a custom-drawn vector would allow — acceptable given the icons used are all simple, common glyphs (bus, train, weather conditions, alerts).

## 11. Design tooling: `tools/layout_editor.html`

**Decision**: the exact pixel layout (positions, sizes, fonts, colors) is maintained as named constants directly in `main.py`'s constants block, consumed by its draw functions — there is no layout config file the app reads or parses at runtime. To make that layout reasonable to iterate on, a standalone, dependency-free HTML tool (`tools/layout_editor.html`) reproduces the layout visually, lets you drag/resize/re-simulate it, and exports coordinates back in a form that can be hand-copied into `main.py`.

**Why not a data-driven layout engine in the app itself**: on a Pi Zero W, an extra layer of layout-config parsing and generic draw dispatch is pure overhead for a screen that has exactly one layout, changed rarely, by one person. Keeping coordinates as constants in the draw functions is the simplest thing that works for the deployed app; the editor tool exists purely to make *designing* those values easier without needing to flash the Pi to see a change. This is a deliberate split: runtime code stays maximally simple, and design-time tooling absorbs the complexity of visualization/iteration.

## 12. Screen dimensions as a single source of truth

**Decision**: `SCREEN_WIDTH`/`SCREEN_HEIGHT` (`main.py:61-62`, currently `800`/`480`) are the one place the panel's pixel dimensions are defined. Every layout constant that depends on the screen size — `COLUMN_OFFSET`, screen-edge margins, the weather section's y-anchor, the timestamp's right-alignment — is either a fixed literal or an expression derived from these two constants at module load, computed once, not re-derived per render call. `DisplayManager.__init__` checks the real hardware's reported `epd.width`/`epd.height` against these constants at startup and raises immediately on a mismatch.

**Why**: earlier, several draw functions (`draw_timestamp`, `draw_weather_section_right`, `draw_train_section`) took `epd_width`/`epd_height` as parameters threaded down from `display_combined_view()`, which read them fresh from the hardware object (`epd.width`, `epd.height`) on every render call. This created two problems in practice: (1) it was easy to pass the wrong one — `draw_train_section`'s "leave room for weather" guard compared a *vertical* `y_offset` against an `epd_width`-derived threshold, a mistake that went unnoticed because the value (600) was simply too large to ever matter on a 480px-tall canvas, so the guard silently never fired; (2) `draw_bus_section` never received the panel width at all, so its journey-header divider line hardcoded `400` — correct only by coincidence, since `400` happens to equal `COLUMN_OFFSET` at the current panel size, with no code-level connection between the two. Neither bug crashed anything or was visible in normal operation, which is exactly why they survived undetected — they only would have surfaced as silent layout corruption if the panel size ever changed.

Collapsing to two constants read directly by every draw function (rather than threaded through call signatures) removes both failure modes at the source: there is now exactly one place to get the axis wrong (there's only one `SCREEN_WIDTH` and one `SCREEN_HEIGHT`, not an `epd_width` parameter that might silently be a height by mistake), and every dependent value is either a named constant or a derivation from these two, not a raw literal that happens to match by coincidence. The startup consistency check in `DisplayManager` exists because this refactor traded a self-correcting design (always re-read from hardware) for a faster, simpler one (trust two constants) — the check is what makes that trade safe: if this code is ever pointed at a different panel, it fails loudly at startup instead of silently drawing a corrupted layout.

**Retargeting to a different panel size**: change `SCREEN_WIDTH`/`SCREEN_HEIGHT` in `main.py` (two lines), matching the driver's `EPD_WIDTH`/`EPD_HEIGHT`. `COLUMN_OFFSET` and every other size-derived constant follow automatically; fixed pixel offsets (margins, gaps, icon sizes) do not scale and would need re-tuning by eye, same as any other layout change — see [screen_layout.md](screen_layout.md) §1 for the full list.

## 13. Four-screen scheduling: fixed precedence over configurable priority, day-type cached once per day

**Decision**: `sleep_screen`, `bus_train_screen`, `daytime_screen`, and `ha_screen` each get an independent daily time window in `schedule_config.json`, but the *order* in which overlapping windows resolve (`sleep_screen` > `bus_train_screen` > `daytime_screen` > `ha_screen`) is fixed in code, not a configurable field. Overlaps aren't validation errors — they're expected and resolved at runtime, with a logged warning naming which screen got overridden.

**Why**: the four screens aren't peers — `sleep_screen` genuinely needs to always win (it's the true "we're overnight, stop polling APIs entirely" state, the "ultimate override" that a misconfigured or overlapping schedule must never be able to suppress), `bus_train_screen` needs to beat `daytime_screen` (a placeholder should never suppress real bus times), and `ha_screen` is deliberately lowest — it's an opportunistic "show the HA dashboard if nothing more important is scheduled" screen, not one that should ever bump real bus times or the daytime placeholder. Making precedence configurable would let a user create a genuinely nonsensical schedule (e.g. `ha_screen` overriding `sleep_screen`) for no real benefit — the four screens have a real hierarchy of importance, not an arbitrary one a config file should be free to invert. Logging the overlap (rather than treating it as a hard validation error) keeps the common case cheap: overlapping windows are actually the expected shape (e.g. `bus_train_screen`'s narrow morning window is deliberately nested inside `daytime_screen`'s broader one), so erroring on every overlap would force awkward non-overlapping schedules just to satisfy the validator. One practical consequence worth noting: `ha_screen`'s default schedule window sits entirely inside `daytime_screen`'s default window, so out of the box `ha_screen` never actually shows — the user needs to carve out a gap in `schedule_config.json` (e.g. narrow `daytime_screen`'s window) if they want it to appear.

**`sleep_screen` is deliberately minimal and local, unlike `ha_screen`**: `sleep_screen` draws directly with PIL (a `MDI.WEATHER_NIGHT` icon + next-wake-time text) rather than fetching anything over the network, whereas `ha_screen` fetches a full HA dashboard screenshot. This is intentional, not an oversight — the "ultimate override" screen must be able to render reliably even if the network, HA, or the Puppeteer add-on it depends on is down; a screen whose entire job is "we're definitely asleep, definitely not polling anything" shouldn't itself depend on the same network it's promising not to poll.

**Day-type resolved once per calendar day, not every loop iteration**: `day_type.DayTypeCache` only re-queries Home Assistant's `binary_sensor.school_day`/`binary_sensor.workday_sensor` when `date.today()` changes from the last resolution, not on every ~30s loop tick. This mirrors the philosophy in §5 (stale-cache-first) but for a different reason: day-type is inherently a once-a-day fact (a day doesn't become "less of a school day" at 10am), so re-querying it every loop iteration would be wasted API calls with no behavioral upside — and worse, if a `binary_sensor.school_day` helper ever flips state mid-morning for any reason, continuously re-resolving it would yank `bus_train_screen` away mid-commute, which is exactly the surprising behavior a display like this must avoid.

## 14. Related documents

- [specifications.md](specifications.md) — what the system does
- [architecture.md](architecture.md) — how it's structured
- [screen_layout.md](screen_layout.md) — the concrete output of the rendering design described in §3, §10, §11
