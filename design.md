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

**Decision**: the exact pixel layout (positions, sizes, fonts, colors) is maintained as literal numbers scattered through `main.py`'s draw functions — there is no layout config file the app reads. To make that layout reasonable to iterate on, a standalone, dependency-free HTML tool (`tools/layout_editor.html`) reproduces the layout visually, lets you drag/resize/re-simulate it, and exports coordinates back in a form that can be hand-copied into `main.py`.

**Why not a data-driven layout engine in the app itself**: on a Pi Zero W, an extra layer of layout-config parsing and generic draw dispatch is pure overhead for a screen that has exactly one layout, changed rarely, by one person. Keeping coordinates as literals in the draw functions is the simplest thing that works for the deployed app; the editor tool exists purely to make *designing* those literals easier without needing to flash the Pi to see a change. This is a deliberate split: runtime code stays maximally simple, and design-time tooling absorbs the complexity of visualization/iteration.

## 12. Related documents

- [specifications.md](specifications.md) — what the system does
- [architecture.md](architecture.md) — how it's structured
- [screen_layout.md](screen_layout.md) — the concrete output of the rendering design described in §3, §10, §11
