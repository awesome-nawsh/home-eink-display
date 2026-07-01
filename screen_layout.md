# Screen Layout — home-eink-display

Pixel-level reference for everything drawn onto the e-ink panel by `app/main.py`. This is the ground truth for exact coordinates, fonts, colors, and draw order — use it alongside `tools/layout_editor.html`, which reproduces this layout interactively (drag/resize/simulate/export) for design iteration.

**Keep this file in sync with `main.py` and `tools/layout_editor.html`'s `DEFAULT_ELEMENTS`** whenever the layout changes — they should never drift from each other.

---

## 1. Canvas

- **Dimensions**: 800 × 480px (`EPD_WIDTH`/`EPD_HEIGHT`, `lib/waveshare_epd/epd7in5b_V2.py:35-36`), landscape, no rotation.
- **Two image buffers**, both 800×480, mode `'1'` (1-bit), background white (255):
  - `black_image` / `draw` — anything drawn here renders **black**.
  - `red_image` / `draw_r` — anything drawn here renders **red**.
  - The panel composites both at refresh time. There is no way to draw a third color or blend — every element must be assigned to exactly one buffer.
- **Layout constants** (`main.py:55-72`):

  ```python
  COLUMN_WIDTH_RATIO = 0.5
  BUS_BOX_HEIGHT = 60
  BUS_BOX_WIDTH = 160
  BUS_BOX_Y_OFFSET = 70        # y_start passed to draw_bus_section; 15px below the header divider at y=55
  BUS_BOX_Y_SPACING = 105
  BUS_NUMBER_FONT_SIZE = 32
  LOAD_FONT_SIZE = 16
  BOTTOM_FONT_SIZE = 14
  BOTTOM_MARGIN = 35
  TOP_MARGIN = 20
  DIVIDER_WIDTH = 2

  FONT_SMALL = 12
  FONT_MEDIUM = 16
  FONT_LARGE = 24
  FONT_XLARGE = 32
  ```

- **Column split**: `column_offset = epd.width // 2` = 400. Left column = bus arrivals. Right column = train status (top) + weather (bottom).

## 2. Fonts

| Key | File | Weight | Used for |
|---|---|---|---|
| Regular | `pic/AtkinsonHyperlegibleNext-Regular.otf` | 400 | Body text, arrival times, weather/train details |
| Bold | `pic/AtkinsonHyperlegibleNext-Bold.otf` | 700 | Headers, bus numbers |
| Icon | `pic/materialdesignicons-webfont.ttf` | — | All icon glyphs (MDI v7.4.47), drawn as text via the same `draw.text()` path |

Loaded via `get_font(size)`, `get_font_bold(size)`, `get_icon_font(size)` — all `@lru_cache`'d (`main.py:336-357`). Text is never anti-aliased/styled beyond size + weight; there is no italic, underline, or color gradient — color comes entirely from which buffer (`draw` vs `draw_r`) the call targets.

## 3. Layout — `display_combined_view()` draw order (`main.py:1254-1293`)

This is the "awake" screen — the primary, most-seen layout. Elements are listed in the order they're actually drawn (paint order matters: later elements can visually overlap earlier ones, though in practice nothing overlaps here).

### 3.1 Header

| # | Element | Coords | Color | Font | Source |
|---|---|---|---|---|---|
| 1 | Bus marker icon | `(15, 5)`, size 50 | Black | Icon, 50pt | `display_combined_view()`, ~1267 |
| 2 | Timestamp ("Updated: HH:MM") | right-aligned to `epd_width - 15`, y=10 | Red | Regular, 18pt | `draw_timestamp()`, 1014-1037 |
| 2b | Date line | below timestamp, y=32, right-aligned | Red | Regular, 12pt | same |
| 3 | Left header text (`HEADER_A`/`A_HEADER` env var, default "Bus Stop") | `(80, 18)` | Red | Bold, 28pt | `display_combined_view()`, ~1276 |
| 4 | Left header divider | `(10, 55)` → `(column_offset-10, 55)`, width 1 | Red | — | ~1278 |
| 5 | Center vertical divider | `(400, 60)` → `(400, epd_height-10)`, width 2 | Red | — | ~1273-1274 |

### 3.2 Bus column (left, `draw_bus_section()`, `main.py:1039-1128`)

Loop starts at `y_start=70`, each service's row occupies `BUS_BOX_Y_SPACING=105px` vertically.

**Optional journey header** (only if `SHOW_JOURNEY_TIME=true`), drawn once above the bus list:
- Icon `MDI.MAP_MARKER_DISTANCE` at `(25, header_y)`, size 20, **red**.
- Text `"Journeys to: {dest}"` at `(50, header_y+2)`, Regular 16pt, **black**.
- Divider `(20, header_y+26)` → `(400, header_y+26)`, width 1, **black**.
- Adds 35px to the starting y if present.

**Per bus service** (row `N`, `box_top = y_start + N*105 + 10`):

| Sub-element | Coords | Color | Font |
|---|---|---|---|
| Bus number box (filled rect) | `(20, box_top)` → `(180, box_top+60)` | Black fill | — |
| Bus number (punched white text) | centered in box | White (fill=255, on black) | Bold, 32pt |
| Arrival times (e.g. `"3 \| 15 \| 28"`, `"Arr"` for ≤0 min) | `(200, ~vertical center of box)` | Black | passed-in font, default Regular 32pt |
| Load icon | `(195, load_text_y-2)`, size 16 | Red | Icon |
| Load text (e.g. "Seats", "Standing", "Limited") | `(213, load_text_y)` (or `(200, ...)` if no icon) | Red | Regular, 16pt |
| Load bar track (white slot) | `(150, box_top+5)` → `(170, box_top+55)` | White (erase, on black draw) | — |
| Load bar fill | `(150, box_top+55-fillH)` → `(170, box_top+55)` | Red | — |

Load bar fill height driven by `BUS_LOAD_MAP_SIZE` (`main.py:52`): `SEA` (Seats Available) = 10px, `SDA` (Standing Available) = 50px, `LSD` (Limited Standing) = 90px — visually clamped to the ~50px track in practice.

**Optional journey time** (per service, if in `journey_times` dict):
- Icon `MDI.TIMER` at `(25, journey_y)` where `journey_y = box_top + 68`, size 18, **red**.
- Text `"{total}min (arrive ~{arrival})"` at `(48, journey_y+2)`, Regular 18pt, **black**.

Default row count shown: **3 bus boxes** (`bus_box_1/2/3` at y=80/185/290) — actual count depends on however many distinct `Services[]` LTA returns for the configured bus stop; more services simply extend the loop further down the column (no hard cap in the draw code, but screen real estate runs out around 4 rows).

### 3.3 Footer

| Element | Coords | Color | Condition |
|---|---|---|---|
| Home Automation/MQTT icon | `(epd.width-70, epd.height-70)`, size 50 | Red | Only drawn if `mqtt_connected` — absent entirely otherwise |

### 3.4 Train column (right, top — `draw_train_section()`, `main.py:1191-1252`)

`train_x = column_offset + 20` = 420.

**Header:**
| Element | Coords | Color | Font |
|---|---|---|---|
| Subway icon | `(train_x-5, 8)` = `(415, 8)`, size 40 | Black | Icon |
| "Train Status" | `(train_x+45, 18)` = `(465, 18)` | Red | Bold, 28pt |
| Divider | `(train_x, 55)` → `(epd_width-10, 55)`, width 1 | Red | — |

**Body — no disruptions** (`train_font = get_font(20)`, `y_offset` starts at 70):
- Check-circle-outline icon at `(train_x, y_offset)`, size 24, **red**.
- 4 lines, Regular 20pt, **black**, at `train_x+30`, spaced +32/+32/+28/+32:
  `"All trains running"` / `"smoothly today!"` / `"No disruptions"` / `"expected."`

**Body — disruptions present** (loop per disruption):
- Alert-circle-outline icon at `(train_x, y_offset)`, size 20, **red**.
- `"Line: {Line}"` at `(train_x+25, y_offset)`, Regular 20pt, **red**; +32.
- `"Dir: {Direction}"`, Regular 20pt, **black**; +32.
- Affected-station list, wrapped to 22 chars, up to 2 lines, Regular 16pt, **black**, +24 each.
- +15px gap between disruptions; loop breaks if `y_offset > epd_height - WEATHER_SECTION_HEIGHT` (340) — the room guard that keeps disruption text from overlapping the weather section, anchored to where the weather divider actually starts.
- If `train_info['content']` present and room allows: divider (**red**), "Alert:" icon+label (Regular 16pt, **red**), then wrapped advisory text, up to 3 lines, Regular 14pt, **black**, +22 each.

This section's real footprint is dynamic — the box shown in the layout tool (`train_body`, `y=70, h=190`) is an approximate placeholder, not a fixed bound.

### 3.5 Weather section (right, bottom — `draw_weather_section_right()`, `main.py:1155-1189`)

`x_start = train_x` = 420. Anchored from the bottom: `weather_y = epd_height - 140` = 340.

| Element | Coords | Color | Font |
|---|---|---|---|
| Divider | `(420, 340)` → `(epd_width-10, 340)`, width 1 | Red | — |
| "Weather" header | `(420, 355)` | Black | Bold, 20pt |
| Condition icon (varies by `get_weather_icon()`) | `(420, 383)`, size 35 | Black | Icon |
| Temperature (`"{temp}°C"`) | `(465, 388)` | Red | Regular, 24pt (`FONT_LARGE`) |
| Condition text (truncated to 15 chars) | `(420, 423)` | Black | Regular, 16pt (`FONT_MEDIUM`) |
| Humidity icon (`MDI.WATER_PERCENT`) | `(420, 448)`, size 18 | Red | Icon |
| Humidity text (`"{humidity}%"`) | `(443, 448)` | Red | Regular, 14pt |

**Note**: `draw_weather_section()` (`main.py:1130-1153`) is a second, bottom-*left*-column weather layout variant that exists in the code but is **never called** by `display_combined_view()` — treat it as dead code, not an active alternate layout, unless it's intentionally revived.

## 4. Alternate full-screen states (not part of the combined view)

These replace the entire screen rather than composing with the layout above.

| Screen | Function | When shown | Notable content |
|---|---|---|---|
| Boot screen | inline in `main()`, ~1469-1478 | Once, at process startup (unless `DEBUG_SKIP_TIME_CHECK=true`) | Bus marker icon `(15,5)` size 50 black; `"System Starting..."` at `(85,18)`, Bold 24pt, black; `"Booted: {time}"` centered-ish, Regular 18pt, red |
| Debug screen | `display_debug_screen()`, 1295-1358 | 5 seconds at boot, only if `DEBUG_SKIP_TIME_CHECK=true` | Two-column dump of every resolved env/config value. Header icon `(15,5)` size 40 black; `"DEBUG MODE"` `(70,15)` red bold 28pt; divider `(10,50)→(epd.width-10,50)` width 2 red; body two columns (x=15 / x=column_split+10), y starts at 60, 17px line spacing, Regular 11pt black; footer `"Displaying for 5 seconds..."` `(15, epd.height-25)` red 14pt |
| Sleep screen | `display_sleep_screen()`, 1360-1387 | Outside the wake window (`is_in_wake_window()` false) | Not drawn via PIL primitives — fetches a full-canvas screenshot of an HA Lovelace dashboard (via a Puppeteer HA add-on), converts to grayscale, pushes directly to the black buffer. Red buffer stays blank white. Not represented in `tools/layout_editor.html` (it's an external image, not a coordinate layout). |

## 5. Design tooling

`tools/layout_editor.html` is a standalone, dependency-free HTML/JS tool that mirrors section 3 of this document visually:

- Canvas sized exactly 800×480 with a 5px-snap grid.
- One draggable/resizable box per element in the table above, tagged with its source function + line range, color, and font (family/style/size/alignment) — editable live.
- Black/Red/Both layer toggle to preview each buffer independently or composited (black painted over red, matching the physical panel).
- Simulated-preview mode renders realistic fake content (sample bus numbers, load bars, weather, train status) using the actual fonts (Atkinson Hyperlegible Next + Material Design Icons, loaded from CDN for preview purposes only) instead of abstract placeholder boxes.
- Export to JSON (round-trippable) or annotated Python-coordinate comments, for hand-porting changes back into `main.py`'s draw functions.

Use it to prototype layout changes before editing `main.py` — then update this document's tables to match whatever you land on.

## 6. Related documents

- [specifications.md](specifications.md) — features these elements support
- [architecture.md](architecture.md) — how the render loop invokes this layout
- [design.md](design.md) — §3 (two-buffer model), §10 (font/icon strategy), §11 (layout tooling) explain *why* this layout works the way it does
