# Screen Layout — home-eink-display

Pixel-level reference for everything drawn onto the e-ink panel by `app/main.py`. This is the ground truth for exact coordinates, fonts, colors, and draw order — use it alongside `tools/layout_editor.html`, which reproduces this layout interactively (drag/resize/simulate/export) for design iteration.

**Keep this file in sync with `main.py` and `tools/layout_editor.html`'s `DEFAULT_ELEMENTS`** whenever the layout changes — they should never drift from each other.

---

## 1. Canvas

- **Dimensions**: 800 × 480px, landscape, no rotation. `SCREEN_WIDTH`/`SCREEN_HEIGHT` (`main.py:61-62`) are the single source of truth for this — they must match `EPD_WIDTH`/`EPD_HEIGHT` in `lib/waveshare_epd/epd7in5b_V2.py:35-36`. `DisplayManager.__init__` (`main.py:1051-1069`) checks the real hardware's reported size against these constants at startup and raises immediately if they've drifted apart, since every draw function reads `SCREEN_WIDTH`/`SCREEN_HEIGHT` directly rather than querying the panel object.
- **To retarget this code at a different panel size**: change `SCREEN_WIDTH`/`SCREEN_HEIGHT` in `main.py` (two lines) and re-derive `COLUMN_OFFSET` (already computed automatically from them via `COLUMN_WIDTH_RATIO`). Everything else — bus box positions, column split, margins, font sizes — is either a fixed offset from an edge/another constant or untouched, so nothing else needs to change for the layout to remain internally consistent at a new size (though the specific pixel values in this document describe the 800×480 layout and would need re-deriving for a different size).
- **Two image buffers**, both `SCREEN_WIDTH`×`SCREEN_HEIGHT`, mode `'1'` (1-bit), background white (255):
  - `black_image` / `draw` — anything drawn here renders **black**.
  - `red_image` / `draw_r` — anything drawn here renders **red**.
  - The panel composites both at refresh time. There is no way to draw a third color or blend — every element must be assigned to exactly one buffer.
- **Layout constants** (`main.py:55-125ish`) — every coordinate/size/spacing value used across the draw functions is a named constant; there are no bare pixel literals left in the render code except a small number of genuinely one-off font-metric nudges (documented inline in `main.py` where they occur). Grouped by area:

  ```python
  # Core screen/box/column
  SCREEN_WIDTH = 800         # single source of truth — must match the driver's EPD_WIDTH
  SCREEN_HEIGHT = 480        # single source of truth — must match the driver's EPD_HEIGHT
  COLUMN_WIDTH_RATIO = 0.5
  COLUMN_OFFSET = int(SCREEN_WIDTH * COLUMN_WIDTH_RATIO)  # derived, not hand-set
  BUS_BOX_HEIGHT = 60
  BUS_BOX_WIDTH = 160
  BUS_BOX_Y_OFFSET = 70      # y_start for draw_bus_section
  BUS_BOX_Y_SPACING = 105
  BUS_NUMBER_FONT_SIZE = 32
  LOAD_FONT_SIZE = 16
  BOTTOM_FONT_SIZE = 14
  BOTTOM_MARGIN = 35
  TOP_MARGIN = 20
  DIVIDER_WIDTH = 2
  WEATHER_SECTION_HEIGHT = 140

  # Font sizes
  FONT_SMALL = 12
  FONT_MEDIUM = 16
  FONT_LARGE = 24
  FONT_XLARGE = 32
  FONT_TIMESTAMP = 18   # timestamp, journey-time line, boot "Booted:" text
  FONT_SECTION = 20     # weather header (bold) / train body font size
  FONT_HEADER = 28      # bold section title: bus/train headers, DEBUG MODE

  # Header (shared by boot screen, main view, debug screen)
  HEADER_ICON_X = 15
  HEADER_ICON_Y = 5
  HEADER_ICON_SIZE = 50
  HEADER_DIVIDER_Y = 55
  HEADER_TEXT_Y = 18
  COLUMN_DIVIDER_TOP_Y = 60
  TRAIN_COLUMN_INDENT = 20

  # Bus section
  BUS_SECTION_X = 20
  BUS_BOX_TOP_GAP = 10
  BUS_TIMES_X = 200
  BUS_LOAD_ICON_X = 195
  BUS_LOAD_TEXT_X = 213
  BUS_LOAD_BAR_X1 = 150
  BUS_LOAD_BAR_X2 = 170
  JOURNEY_ICON_X = 25
  JOURNEY_HEADER_GAP = 35
  LOAD_TEXT_Y_NUDGE = 8
  JOURNEY_Y_GAP = 8

  # Train section
  TRAIN_SECTION_Y_OFFSET = 70
  TRAIN_LINE_SPACING = 32
  TRAIN_LINE_SPACING_SMALL = 28
  TRAIN_WRAP_WIDTH = 22
  TRAIN_STATION_LINE_SPACING = 24
  TRAIN_ALERT_LINE_SPACING = 22
  TRAIN_DISRUPTION_GAP = 15
  ALERT_SECTION_GAP = 10
  ALERT_POST_DIVIDER_GAP = 15

  # Weather section
  WEATHER_POST_DIVIDER_GAP = 15
  WEATHER_HEADER_GAP = 28

  # Screen edges
  SCREEN_MARGIN = 10
  TEXT_RIGHT_MARGIN = 15
  ```

  Note: `TRAIN_SECTION_Y_OFFSET` is a deliberately separate constant from `BUS_BOX_Y_OFFSET`, even though both are currently `70` — the bus and train columns are independently tunable, not the same value by design.

- **Column split**: `column_offset = epd.width // 2` = 400. Left column = bus arrivals. Right column = train status (top) + weather (bottom).

## 2. Fonts

| Key | File | Weight | Used for |
|---|---|---|---|
| Regular | `pic/AtkinsonHyperlegibleNext-Regular.otf` | 400 | Body text, arrival times, weather/train details |
| Bold | `pic/AtkinsonHyperlegibleNext-Bold.otf` | 700 | Headers, bus numbers |
| Icon | `pic/materialdesignicons-webfont.ttf` | — | All icon glyphs (MDI v7.4.47), drawn as text via the same `draw.text()` path |

Loaded via `get_font(size)`, `get_font_bold(size)`, `get_icon_font(size)` — all `@lru_cache`'d (`main.py:397-418`). Text is never anti-aliased/styled beyond size + weight; there is no italic, underline, or color gradient — color comes entirely from which buffer (`draw` vs `draw_r`) the call targets.

## 3. Layout — `display_combined_view()` draw order (`main.py:1297-1333`)

This is the "awake" screen — the primary, most-seen layout. Elements are listed in the order they're actually drawn (paint order matters: later elements can visually overlap earlier ones, though in practice nothing overlaps here).

### 3.1 Header

| # | Element | Coords | Color | Font | Source |
|---|---|---|---|---|---|
| 1 | Bus marker icon | `(HEADER_ICON_X, HEADER_ICON_Y)` = `(15, 5)`, size `HEADER_ICON_SIZE` (50) | Black | Icon, 50pt | `display_combined_view()`, 1308 |
| 2 | Timestamp ("Updated: HH:MM") | right-aligned to `SCREEN_WIDTH - TEXT_RIGHT_MARGIN`, y=10 | Red | Regular, `FONT_TIMESTAMP` (18) | `draw_timestamp()`, 1081-1104 |
| 2b | Date line | below timestamp, y=32, right-aligned | Red | Regular, `FONT_SMALL` (12) | same |
| 3 | Left header text (`HEADER_A`/`A_HEADER` env var, default "Bus Stop") | `(80, HEADER_TEXT_Y)` = `(80, 18)` | Red | Bold, `FONT_HEADER` (28) | `display_combined_view()`, 1318 |
| 4 | Left header divider | `(SCREEN_MARGIN, HEADER_DIVIDER_Y)` → `(COLUMN_OFFSET - SCREEN_MARGIN, HEADER_DIVIDER_Y)`, width 1 | Red | — | 1319 |
| 5 | Center vertical divider | `(COLUMN_OFFSET, COLUMN_DIVIDER_TOP_Y)` → `(COLUMN_OFFSET, SCREEN_HEIGHT - SCREEN_MARGIN)`, width `DIVIDER_WIDTH` (2) | Red | — | 1314-1315 |

`COLUMN_OFFSET` (= `int(SCREEN_WIDTH * COLUMN_WIDTH_RATIO)` = 400 at 800×480) is computed once at module load — see §1 above.

### 3.2 Bus column (left, `draw_bus_section()`, `main.py:1106-1195`)

Loop starts at `y_start=BUS_BOX_Y_OFFSET` (70), each service's row occupies `BUS_BOX_Y_SPACING=105px` vertically.

**Optional journey header** (only if `SHOW_JOURNEY_TIME=true`), drawn once above the bus list:
- Icon `MDI.MAP_MARKER_DISTANCE` at `(JOURNEY_ICON_X, header_y)` = `(25, header_y)`, size 20, **red**.
- Text `"Journeys to: {dest}"` at `(50, header_y+2)`, Regular 16pt (`FONT_MEDIUM`), **black**.
- Divider `(BUS_SECTION_X, header_y+26)` → `(COLUMN_OFFSET, header_y+26)`, width 1, **black**.
- Adds `JOURNEY_HEADER_GAP` (35px) to the starting y if present.

**Per bus service** (row `N`, `box_top = y_start + N*BUS_BOX_Y_SPACING + BUS_BOX_TOP_GAP`):

| Sub-element | Coords | Color | Font |
|---|---|---|---|
| Bus number box (filled rect) | `(BUS_SECTION_X, box_top)` → `(BUS_SECTION_X+BUS_BOX_WIDTH, box_top+BUS_BOX_HEIGHT)` = `(20, box_top)` → `(180, box_top+60)` | Black fill | — |
| Bus number (punched white text) | centered in box | White (fill=255, on black) | Bold, `BUS_NUMBER_FONT_SIZE` (32) |
| Arrival times (e.g. `"3 \| 15 \| 28"`, `"Arr"` for ≤0 min) | `(BUS_TIMES_X, ~vertical center of box)` = `(200, ...)` | Black | passed-in font, default Regular 32pt |
| Load icon | `(BUS_LOAD_ICON_X, load_text_y-2)` = `(195, ...)`, size `LOAD_FONT_SIZE` (16) | Red | Icon |
| Load text (e.g. "Seats", "Standing", "Limited") | `(BUS_LOAD_TEXT_X, load_text_y)` = `(213, ...)` (or `BUS_TIMES_X` if no icon) | Red | Regular, `LOAD_FONT_SIZE` (16) |
| Load bar track (white slot) | `(BUS_LOAD_BAR_X1, box_top+5)` → `(BUS_LOAD_BAR_X2, box_top+55)` = `(150, ...)` → `(170, ...)` | White (erase, on black draw) | — |
| Load bar fill | `(150, box_top+55-fillH)` → `(170, box_top+55)` | Red | — |

Load bar fill height driven by `BUS_LOAD_MAP_SIZE` (`main.py:52`): `SEA` (Seats Available) = 10px, `SDA` (Standing Available) = 50px, `LSD` (Limited Standing) = 90px — visually clamped to the ~50px track in practice.

**Optional journey time** (per service, if in `journey_times` dict):
- Icon `MDI.TIMER` at `(JOURNEY_ICON_X, journey_y)` where `journey_y = box_top + box_height + JOURNEY_Y_GAP`, size 18, **red**.
- Text `"{total}min (arrive ~{arrival})"` at `(48, journey_y+2)`, Regular `FONT_TIMESTAMP` (18), **black**.

Default row count shown: **3 bus boxes** (`bus_box_1/2/3` at y=80/185/290) — actual count depends on however many distinct `Services[]` LTA returns for the configured bus stop; more services simply extend the loop further down the column (no hard cap in the draw code, but screen real estate runs out around 4 rows).

### 3.3 Footer

| Element | Coords | Color | Condition |
|---|---|---|---|
| Home Automation/MQTT icon | `(SCREEN_WIDTH-70, SCREEN_HEIGHT-70)`, size `HEADER_ICON_SIZE` (50) | Red | Only drawn if `mqtt_connected` — absent entirely otherwise |

### 3.4 Train column (right, top — `draw_train_section()`, `main.py:1233-1295`)

`train_x = COLUMN_OFFSET + TRAIN_COLUMN_INDENT` = 420. `draw_train_section()` takes only `(draw, draw_r, train_info, train_x)` — it reads `SCREEN_WIDTH`/`SCREEN_HEIGHT` directly rather than being passed the panel size.

**Header:**
| Element | Coords | Color | Font |
|---|---|---|---|
| Subway icon | `(train_x-5, 8)` = `(415, 8)`, size 40 | Black | Icon |
| "Train Status" | `(train_x+45, HEADER_TEXT_Y)` = `(465, 18)` | Red | Bold, `FONT_HEADER` (28) |
| Divider | `(train_x, HEADER_DIVIDER_Y)` → `(SCREEN_WIDTH - SCREEN_MARGIN, HEADER_DIVIDER_Y)`, width 1 | Red | — |

**Body — no disruptions** (`train_font = get_font(FONT_SECTION)` = 20pt, `y_offset` starts at `TRAIN_SECTION_Y_OFFSET` = 70):
- Check-circle-outline icon at `(train_x, y_offset)`, size 24, **red**.
- 4 lines, Regular 20pt, **black**, at `train_x+30`, spaced `TRAIN_LINE_SPACING`/`TRAIN_LINE_SPACING`/`TRAIN_LINE_SPACING_SMALL`/`TRAIN_LINE_SPACING` (+32/+32/+28/+32):
  `"All trains running"` / `"smoothly today!"` / `"No disruptions"` / `"expected."`

**Body — disruptions present** (loop per disruption):
- Alert-circle-outline icon at `(train_x, y_offset)`, size 20, **red**.
- `"Line: {Line}"` at `(train_x+25, y_offset)`, Regular 20pt, **red**; `+TRAIN_LINE_SPACING` (32).
- `"Dir: {Direction}"`, Regular 20pt, **black**; `+TRAIN_LINE_SPACING` (32).
- Affected-station list, wrapped to `TRAIN_WRAP_WIDTH` (22) chars, up to 2 lines, Regular 16pt, **black**, `+TRAIN_STATION_LINE_SPACING` (24) each.
- `+TRAIN_DISRUPTION_GAP` (15px) gap between disruptions; loop breaks if `y_offset > SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT` (340) — the room guard that keeps disruption text from overlapping the weather section, anchored to where the weather divider actually starts. (Previously compared against the panel's *width* instead of its *height* and could never trigger — fixed alongside the `SCREEN_WIDTH`/`SCREEN_HEIGHT` cleanup.)
- If `train_info['content']` present and room allows: divider (**red**), "Alert:" icon+label (Regular 16pt, **red**), then wrapped advisory text, up to 3 lines, Regular 14pt, **black**, `+TRAIN_ALERT_LINE_SPACING` (22) each.

This section's real footprint is dynamic — the box shown in the layout tool (`train_body`, `y=70, h=190`) is an approximate placeholder, not a fixed bound.

### 3.5 Weather section (right, bottom — `draw_weather_section_right()`, `main.py:1197-1231`)

`x_start = train_x` = 420. Anchored from the bottom: `weather_y = SCREEN_HEIGHT - WEATHER_SECTION_HEIGHT` = 340. Like `draw_train_section()`, this function takes only `(draw, draw_r, weather_info, x_start)` — no panel-size params.

| Element | Coords | Color | Font |
|---|---|---|---|
| Divider | `(x_start, weather_y)` → `(SCREEN_WIDTH - SCREEN_MARGIN, weather_y)` = `(420, 340)` → `(790, 340)`, width 1 | Red | — |
| "Weather" header | `(420, 355)` | Black | Bold, `FONT_SECTION` (20) |
| Condition icon (varies by `get_weather_icon()`) | `(420, 383)`, size 35 | Black | Icon |
| Temperature (`"{temp}°C"`) | `(465, 388)` | Red | Regular, 24pt (`FONT_LARGE`) |
| Condition text (truncated to 15 chars) | `(420, 423)` | Black | Regular, 16pt (`FONT_MEDIUM`) |
| Humidity icon (`MDI.WATER_PERCENT`) | `(420, 448)`, size 18 | Red | Icon |
| Humidity text (`"{humidity}%"`) | `(443, 448)` | Red | Regular, 14pt (`BOTTOM_FONT_SIZE`) |
| PSI icon (`MDI.LEAF`) | `(510, 448)`, size 18 (x = humidity x + 90; at 420 if no humidity) | Black | Icon |
| PSI text (`"PSI {psi}"`, NEA 24h worst region; omitted if unavailable) | `(533, 448)` | Black | Regular, 14pt (`BOTTOM_FONT_SIZE`) |

## 4. Alternate full-screen states (not part of the combined view)

These replace the entire screen rather than composing with the layout above.

| Screen | Function | When shown | Notable content |
|---|---|---|---|
| Boot checklist | `display_boot_checklist()`, `app/render/boot_screen.py` | Once, at process startup (unless `DEBUG_SKIP_TIME_CHECK=true`) | Bus marker icon `(HEADER_ICON_X, HEADER_ICON_Y)` size `HEADER_ICON_SIZE` black; `"System Starting..."` at `(85, HEADER_TEXT_Y)`, Bold `FONT_HEADER` (28), black; divider at y=55; then one row per connectivity check (Network/Internet/LTA API/Home Assistant), each a `CHECK_CIRCLE`/`ALERT_CIRCLE` icon (24pt, black) + label (Regular 20pt, black), 34px row spacing starting at y=80; footer `"Booted: {time}"` centered at `(SCREEN_WIDTH/2, SCREEN_HEIGHT-25)`, Regular `FONT_TIMESTAMP` (18), red. All four checks run before this single draw+display() call — never one physical refresh per check. |
| Debug screen | `display_debug_screen()`, `app/render/debug_screen.py` | 5 seconds at boot, only if `DEBUG_SKIP_TIME_CHECK=true` | Two-column dump of every resolved env/config value. Header icon `(HEADER_ICON_X, HEADER_ICON_Y)` size 40 black; `"DEBUG MODE"` `(70,15)` red bold `FONT_HEADER` (28); divider `(SCREEN_MARGIN,50)→(SCREEN_WIDTH-SCREEN_MARGIN,50)` width `DIVIDER_WIDTH` (2) red; body two columns (x=15 / x=`COLUMN_OFFSET`+10), y starts at 60, 17px line spacing, Regular 11pt black; footer `"Displaying for 5 seconds..."` `(15, SCREEN_HEIGHT-25)` red `BOTTOM_FONT_SIZE` (14) |
| `sleep_screen` | `display_sleep_screen()`, `app/render/sleep_screen.py` (new in Phase 2 — the true overnight screen) | Per its own `schedule_config.json` window (default ~21:00–06:00) — **highest precedence of all four scheduled screens ("ultimate override")** | Minimal local draw, no network fetch: `MDI.WEATHER_NIGHT` icon centered at `(SCREEN_WIDTH/2, SCREEN_HEIGHT/2-40)`, size 80, black, `anchor="mm"`; `"Next wake: {HH:MM}"` centered at `(SCREEN_WIDTH/2, SCREEN_HEIGHT/2+60)`, Regular `FONT_SECTION` (20), red, `anchor="mm"` (the wake time is `scheduler.get_next_wake_time()` — `sleep_screen`'s own configured `end` time). Only redrawn on screen-entry or manual refresh, not every loop tick. |
| `daytime_screen` | `display_daytime_screen()`, `app/render/daytime_screen.py` | Per its own `schedule_config.json` window — beats `ha_screen` on overlap and is the safe fallback when no window matches at all; shown when `sleep_screen` isn't active and `bus_train_screen` isn't eligible/scheduled | Word clock + date + weather, all centered on `SCREEN_WIDTH/2`: time-in-words (e.g. `"Quarter past two"`) at y=150, Bold `FONT_CLOCK` (64), black, `anchor="mm"`; date (`"Thursday 2 July"`) at y=245, Regular `FONT_HEADER` (28), black; weather row at y=360 — condition icon (48px, black) + temperature (Bold 32, **red**) centered as one group, then `"{Condition}  ·  {humidity}%  ·  PSI {psi}"` at y=415, Regular `FONT_SECTION` (20), black (humidity/PSI parts dropped individually when unavailable). Weather row omitted entirely when weather is unavailable. Redrawn only when the quarter-hour bucket or weather changes (4 refreshes/hour, aligned :00/:15/:30/:45), not every loop tick. |
| `ha_screen` | `display_ha_screen()`, `app/render/ha_screen.py` (renamed from `display_sleep_screen()` earlier in Phase 2, before the true `sleep_screen` above existed) | Per its own `schedule_config.json` window (default a one-hour evening slot) — **lowest precedence of all four**; only shows in a genuine gap none of the other three claim | Not drawn via PIL primitives — fetches a full-canvas screenshot of an HA Lovelace dashboard (via a Puppeteer HA add-on) sized to `display_mgr.epd.width`/`height` (the real hardware-reported size, which `DisplayManager` guarantees matches `SCREEN_WIDTH`/`SCREEN_HEIGHT`), converts to grayscale, pushes directly to the black buffer. Red buffer stays blank white. Not represented in `tools/layout_editor.html` (it's an external image, not a coordinate layout; the tool's tab is still named "Sleep screen" — see `todo.md`). Only re-fetched on entry into this screen or a manual refresh — not polled every loop iteration. |

**Note**: the previously-flagged dead `draw_weather_section()` (a second, bottom-*left*-column weather layout variant) has been removed from the codebase — `draw_weather_section_right()` is the only weather renderer now.

## 5. Design tooling

`tools/layout_editor.html` is a standalone, dependency-free HTML/JS tool that mirrors sections 3-4 of this document visually, with a screen switcher covering all three states the app actually renders through coordinates or images:

- **Regular display** tab — mirrors §3 in full: one draggable/resizable box per element, tagged with its source function + line range, color, and font (family/style/size/alignment) — editable live.
- **Boot screen** tab — mirrors §4's boot screen row: the header icon, `"System Starting..."` text, and the red `"Booted: {time}"` text, same editing model as the regular display.
- **Sleep screen** tab — §4's sleep screen has no coordinates (it's an externally-fetched image, not a drawn layout), so this tab instead lets you upload a sample image and see it converted to grayscale exactly as `display_sleep_screen()` would render it to the black buffer (canvas-scaled to 800×480, luminance-weighted grayscale). The red-buffer note and `SLEEP_SCREEN_*` env vars are documented alongside it. The debug screen (§4) isn't modeled — it's a dev-only env-var dump, not a layout worth prototyping visually.
- Canvas sized exactly 800×480 with a 5px-snap grid (element screens only).
- Black/Red/Both layer toggle to preview each buffer independently or composited (black painted over red, matching the physical panel) — on the sleep screen this correctly shows nothing in "Red only" mode, since that buffer is always blank for that screen.
- Simulated-preview mode renders realistic fake content (sample bus numbers, load bars, weather, train status, boot time) using the actual fonts (Atkinson Hyperlegible Next + Material Design Icons, loaded from CDN for preview purposes only) instead of abstract placeholder boxes.
- Export to JSON (round-trippable) or annotated Python-coordinate comments, for hand-porting changes back into `main.py`'s draw functions — scoped to whichever screen tab is active.

Each element/image screen keeps its own edit state independently, so you can switch tabs without losing in-progress changes. Use it to prototype layout changes before editing `main.py` — then update this document's tables to match whatever you land on.

## 6. Related documents

- [specifications.md](specifications.md) — features these elements support
- [architecture.md](architecture.md) — how the render loop invokes this layout
- [design.md](design.md) — §3 (two-buffer model), §10 (font/icon strategy), §11 (layout tooling), §12 (`SCREEN_WIDTH`/`SCREEN_HEIGHT` as a single source of truth) explain *why* this layout works the way it does
