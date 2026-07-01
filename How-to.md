# How-To — Setting Up Your Own e-ink Bus Display

Practical, step-by-step setup guide for running this project on your own Raspberry Pi. For the *why* behind design decisions see [design.md](design.md); for the full feature/config reference see [specifications.md](specifications.md); for how the code is structured see [architecture.md](architecture.md).

---

## 1. What you need

**Hardware:**
- Raspberry Pi Zero W or Zero 2 W, with GPIO header pins
- Waveshare 7.5" e-ink display, B/W/R model (`epd7in5b_V2` driver)
- A GPIO HAT for the Waveshare panel (avoids soldering)
- A picture frame or enclosure of your choice
- Power supply for the Pi

**Accounts / API keys:**
- LTA DataMall API key — register at [datamall.lta.gov.sg](https://datamall.lta.gov.sg/content/datamall/en/request-for-api.html) (required — this is what the bus/train data comes from)
- A routing API, for journey-time estimates (optional feature):
  - [OneMap](https://www.onemap.gov.sg/apidocs/) (free, Singapore-specific), or
  - Google Maps Directions API (requires a Google Cloud project + billing)
- A running Home Assistant instance (optional, but needed for weather, the `ha_screen` dashboard, and day-type detection):
  - A long-lived access token (Profile → Long-Lived Access Tokens)
  - The [Puppeteer add-on](https://github.com/mikefarmer01/hassio-addons) if you want `ha_screen`'s dashboard screenshot
  - `binary_sensor.school_day` / `binary_sensor.workday_sensor` (or equivalents) if you want day-type-gated screens

---

## 2. Get the code onto the Pi

```bash
ssh <user>@<pi-ip>
git clone https://github.com/awesome-nawsh/home-eink-display.git
cd home-eink-display
```

**Optional — exclude `tests/` from the Pi's working tree.** It's completely harmless to leave in place (nothing at runtime imports it, no extra dependencies, negligible disk use), but if you'd rather not have it checked out on the device itself:

```bash
git sparse-checkout init --cone
git sparse-checkout set app images lib pic systemd tools
```

This only affects what's materialized in the working directory — `tests/` stays fully tracked in git history, and `git pull` keeps working normally afterward. Just `rm -rf tests/` on its own won't stick, since a future `git pull` would recreate it; sparse-checkout is the durable way. To bring it back later: `git sparse-checkout disable`.

## 3. Install dependencies

`pigpio` is a system package, not a pip package — install it via `apt` first:

```bash
sudo apt-get install python3-pigpio pigpiod
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

Then the Python dependencies. Modern Raspberry Pi OS (Bookworm+) blocks system-wide `pip install` by default (PEP 668) — `--break-system-packages` is the simplest way around it here, since `pigpio` above is already installed system-wide via apt:

```bash
pip3 install -r requirements.txt --break-system-packages
```

## 4. Configure `.env`

```bash
cp app/.env.example app/.env
```

Edit `app/.env` and fill in at minimum: `API_KEY` (LTA DataMall), `BUS_STOP_CODE_A` (5-digit bus stop code), `A_HEADER` (display label for the stop).

Then generate the two values `web_config.py` requires — it **refuses to start** without real values here (no insecure defaults):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# -> paste as WEB_CONFIG_SECRET_KEY in .env

python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"
# -> paste as WEB_CONFIG_PASSWORD_HASH in .env
```

If you're setting up Home Assistant integration, weather, journey times, or MQTT, fill in the relevant sections of `.env` too — every variable is documented inline in `.env.example`.

**Upgrading an existing `.env` from before Phase 3?** Use the migration helper instead of hand-editing:

```bash
python3 tools/migrate_env.py
```

It backs up your existing `.env`, encrypts plaintext secrets at rest, renames `HOME_ASSISTANT_SLEEP_URL` → `HOME_ASSISTANT_DASHBOARD_URL` (keeping the old key as a fallback), generates `WEB_CONFIG_SECRET_KEY` if missing/placeholder, prompts for a new admin password if `WEB_CONFIG_PASSWORD_HASH` is unset, and creates `schedule_config.json` from the template if you don't have one yet. It shows you exactly what it's about to change before touching anything, and never prints secret values to the terminal.

## 5. Configure the screen schedule (optional)

The display has four screens — `sleep_screen` (overnight), `bus_train_screen` (bus/train view, school-day only), `daytime_screen` (placeholder), `ha_screen` (HA dashboard, lowest priority) — each with its own daily time window in `app/schedule_config.json`. If you skip this step, a schedule is derived automatically from the legacy `WAKE_HOUR`/`SLEEP_HOUR` values in `.env`.

```bash
cp app/schedule_config.json.example app/schedule_config.json
```

Edit the four `start`/`end` times to suit your household. See [specifications.md §3.1](specifications.md) for the exact precedence rules, or just use the web config panel's Schedule page once it's running (§7 below) — it validates your changes and shows any schedule conflicts before you save.

## 6. Deploy the main display service

```bash
sudo cp systemd/bus_display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bus_display
```

Check it's running:

```bash
sudo systemctl status bus_display
journalctl -u bus_display -f
```

You should see a boot connectivity checklist appear on the panel, then the correct screen for the current time/day-type.

## 7. Deploy the web config panel

Lets you edit `.env` and the schedule from a browser instead of SSHing in every time.

```bash
sudo cp systemd/web_config.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now web_config
```

Visit `http://<pi-ip>:5000` and log in with `WEB_CONFIG_USERNAME` (default `admin`) and the password you hashed in step 4.

To let the panel's "Restart Service" button actually restart `bus_display` (needed for most `.env` changes to take effect — config is only loaded once at process start; the schedule and `FORCE_SCREEN` are the exception, see below), it needs a one-time passwordless-sudo entry:

```bash
sudo cp systemd/bus_display_restart.sudoers.example /etc/sudoers.d/bus_display_restart
sudo chmod 440 /etc/sudoers.d/bus_display_restart
sudo visudo -c   # validates the syntax
```

## 8. Verify it's actually working

- `journalctl -u bus_display -f` — confirm clean startup, no import errors, real API calls succeeding (not 404s).
- Set `FORCE_SCREEN=<screen_name>` in `.env` (one of `sleep_screen`, `bus_train_screen`, `daytime_screen`, `ha_screen`) to force any screen on demand, without waiting for its schedule window. Since Phase 4, this and the schedule (`schedule_config.json`) apply live within moments — no restart needed — whether you edit them via the web UI (which pings the running service automatically) or directly in the files over SSH (picked up by a background file-change check). Clear it (`FORCE_SCREEN=`) once you're done testing. Everything else in `.env` still needs a restart.
- If you want to preview layout changes without touching the Pi at all, `python3 tools/preview_render.py --screen <combined|debug|daytime|sleep|boot>` renders any of the local screens to a PNG on your own machine (needs `Pillow`/`python-dotenv` installed locally) — it can't preview `ha_screen`, since that one fetches a live HA dashboard screenshot.

---

## Troubleshooting

- **Bus/train API calls return 404**: LTA DataMall requires `https://`, not `http://`, for some endpoints — double-check `API_BUS_URL`/`API_TRAIN_URL` in `.env` match the `https://` defaults in `.env.example`.
- **Port 5000 already in use**: on some systems (notably macOS, if you're testing `web_config.py` on a dev machine rather than the Pi) something else already listens there — set `WEB_CONFIG_PORT` to something else in `.env`.
- **`web_config.py` refuses to start**: it's telling you exactly what's missing in its startup message — `WEB_CONFIG_SECRET_KEY` and `WEB_CONFIG_PASSWORD_HASH` must both be set to real, non-placeholder values (step 4 above).
- **`/api/restart` fails with a permission error**: the one-time sudoers setup (step 7) hasn't been done yet on this Pi.
- **Panel shows a wrong/blank layout**: confirm `SCREEN_WIDTH`/`SCREEN_HEIGHT` in `app/config.py` match your actual panel's `EPD_WIDTH`/`EPD_HEIGHT` (`lib/waveshare_epd/epd7in5b_V2.py`) — `DisplayManager` checks this at startup and refuses to run on a mismatch.
- **Deeper architecture/behavior questions**: see [architecture.md](architecture.md) (how it's structured), [specifications.md](specifications.md) (what it does), [design.md](design.md) (why), [screen_layout.md](screen_layout.md) (exact pixel layout), and `todo.md` (what's planned but not built yet).
