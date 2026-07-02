# home-eink-display — Claude Code Context

## What This Is
A Raspberry Pi e-ink display that shows Singapore bus arrival times, MRT disruption alerts, weather, and journey-time estimates during the day, an overnight sleep screen, and (optionally) a Home Assistant dashboard screenshot. Adapted from [awesomelionel's project](https://github.com/awesomelionel/singapore-bus-timing-edisplay).

**Current version:** v14 (Phases 1–4 of the module-split/scheduler/web-config rewrite, all merged to `main`)
**Status:** Production, running as two systemd services on a Raspberry Pi Zero W

Setting this up from scratch? See [How-to.md](How-to.md) for the full step-by-step guide. For how the code is structured, why, and exact pixel layout, see [architecture.md](architecture.md), [design.md](design.md), and [screen_layout.md](screen_layout.md) respectively — this file is a quick-orientation doc, not the deep reference.

---

## Hardware
- Raspberry Pi Zero W (user: `pi`, home: `/home/pi/`)
- Waveshare 7.5" e-ink display, B/W/R — driver: `epd7in5b_V2`
- Connected via GPIO HAT (no soldering)
- Pi path: `/home/pi/home-eink-display/`

---

## Directory Structure

```
home-eink-display/
├── app/
│   ├── main.py                 # Entry point / orchestration only — the scheduler loop
│   ├── config.py               # All env vars, layout constants, validate_configuration(),
│   │                           # dynamic-reload support (config.py's own docstring explains this)
│   ├── health.py                # sd_notify (systemd watchdog pings), SystemHealth
│   ├── fetchers.py               # All data-fetch functions, DataCache, BackoffManager, http_session
│   ├── mqtt_client.py             # MQTTClient
│   ├── scheduler.py                # Four-screen scheduling: schedule_config.json load/validate/resolve
│   ├── day_type.py                  # school_day/work_day/off_day resolution (once/calendar day)
│   ├── boot_checks.py                # Boot-time connectivity probes
│   ├── reload_watch.py                # Pure file-mtime-change detection (dynamic reload backstop)
│   ├── secrets_vault.py                # Encrypt/decrypt password-type .env values at rest
│   ├── render/                          # All screen-drawing code (one file per screen + shared helpers)
│   │   ├── common.py                     # DisplayManager, MDI icon table, font loaders
│   │   ├── bus_train.py                   # bus_train_screen
│   │   ├── sleep_screen.py                 # sleep_screen (true overnight screen)
│   │   ├── ha_screen.py                     # ha_screen (HA dashboard screenshot)
│   │   ├── daytime_screen.py                 # daytime_screen (placeholder — see todo.md)
│   │   ├── boot_screen.py                     # Boot connectivity checklist
│   │   └── debug_screen.py                     # Dev-only env-var dump
│   ├── web_config.py                    # Flask app: routes only
│   ├── web_config_schema.py              # CONFIG_SCHEMA (pure data)
│   ├── web_config_env.py                  # Pure .env read/build-updates/atomic-write
│   ├── web_config_schedule_forms.py        # Pure form<->schedule dict conversion + atomic JSON writer
│   ├── templates/, static/                  # Jinja templates + CSS/JS for the web panel
│   ├── schedule_config.json.example          # Template — real file is gitignored, per-deployment
│   ├── .env                                   # NOT in git — your real secrets
│   └── .encryption_key                         # NOT in git — auto-generated, encrypts .env secrets
├── lib/waveshare_epd/                     # Waveshare e-ink driver library (only epd7in5b_V2.py used)
├── pic/                                    # Fonts loaded by PIL at runtime
├── systemd/
│   ├── bus_display.service                 # Main display process
│   ├── web_config.service                    # Web config panel process
│   └── bus_display_restart.sudoers.example    # One-time sudoers setup for /api/restart
├── tools/
│   ├── preview_render.py                    # Render any screen to a PNG, no Pi/hardware needed
│   └── migrate_env.py                        # Migrate an older .env to the current format
├── tests/                                   # stdlib unittest — run via `python -m unittest discover -s tests`
├── images/                                  # Photos of the physical display (docs only)
├── .env.example                             # Template — commit this
├── How-to.md                                 # Step-by-step setup guide for new installs
├── architecture.md, design.md,
│   specifications.md, screen_layout.md         # Deep reference docs
├── todo.md                                    # Running checklist of planned/deferred work
├── ChangeLog.md
└── CLAUDE.md                                   # This file
```

---

## The Four Screens

Since Phase 2, the display cycles through four screens on independent schedules (`app/schedule_config.json`), with a fixed precedence when windows overlap:

`sleep_screen` (overnight, "ultimate override") > `bus_train_screen` (bus/train/weather/journey view, only eligible on a `school_day`) > `daytime_screen` (placeholder, lowest-precedence fallback) > `ha_screen` (HA dashboard screenshot, only shows in an unclaimed gap).

Day-type (`school_day`/`work_day`/`off_day`) is resolved once per calendar day from two Home Assistant `binary_sensor` entities. See `specifications.md` §3.1 and `design.md` §13 for the full precedence/day-type rationale.

`FORCE_SCREEN=<screen_name>` in `.env` forces any one screen regardless of schedule/day-type — useful for testing, and (since Phase 4) applies live without a restart.

---

## Configuration
All configuration is via `.env` (loaded by `python-dotenv`) plus `app/schedule_config.json` (the four screens' time windows). See `.env.example` and `app/schedule_config.json.example` for every variable/field with descriptions.

Key `.env` variables:
- `API_KEY` — LTA DataMall API key (required)
- `BUS_STOP_CODE_A` — 5-digit bus stop code
- `HOME_ASSISTANT_API_URL` / `HOME_ASSISTANT_TOKEN` — HA integration (weather, day-type sensors, `ha_screen`)
- `SHOW_JOURNEY_TIME` — enable/disable commute time estimates
- `WAKE_HOUR` / `SLEEP_HOUR` — **legacy fallback only**, used solely to derive a default schedule if `schedule_config.json` is missing/invalid
- `MQTT_ENABLED` — allow HA to trigger display refreshes and config reloads
- `WEB_CONFIG_SECRET_KEY` / `WEB_CONFIG_PASSWORD_HASH` — **required**, no insecure fallback; `web_config.py` refuses to start without real values here

Most `.env` changes need a restart to apply (`/api/restart` in the web UI, or `sudo systemctl restart bus_display`). Two exceptions apply live, no restart needed: the schedule (`schedule_config.json`) and `FORCE_SCREEN` — see `design.md` §15.

---

## Deploy Workflow (Mac → Pi)

```bash
# 1. Make changes locally and commit
git add .
git commit -m "your message"
git push

# 2. SSH to Pi and pull
ssh pi@<pi-ip>
cd /home/pi/home-eink-display
git pull

# 3. Restart the service(s)
sudo systemctl restart bus_display
sudo systemctl restart web_config   # only if web_config.py changed

# 4. Check it's running
sudo systemctl status bus_display
journalctl -u bus_display -f   # live logs
```

Upgrading an existing deployment's `.env` from an older phase? Run `python3 tools/migrate_env.py` first (backs up `.env`, encrypts plaintext secrets, adds any new required vars).

---

## Service Management (on Pi)

```bash
sudo systemctl start bus_display      # start
sudo systemctl stop bus_display       # stop
sudo systemctl restart bus_display    # restart
sudo systemctl status bus_display     # status + recent logs
journalctl -u bus_display -n 50       # last 50 log lines
journalctl -u bus_display -f          # follow live logs
```

Same commands apply to `web_config` (the web config panel service). Both service files live at `/etc/systemd/system/`. After editing a service file on the Pi, run `sudo systemctl daemon-reload`.

---

## Pi Dependencies (apt, not pip)

```bash
sudo apt-get install python3-pigpio pigpiod
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

Python packages (pip, PEP 668 requires `--break-system-packages` on Bookworm+):
```bash
pip3 install -r requirements.txt --break-system-packages
```

---

## Where the Code Actually Lives

`app/main.py` is thin orchestration only (~250 lines) — the scheduler loop, boot sequence, cleanup/signal handling. Everything else is in focused sibling modules; see the Directory Structure above for what's where, or `architecture.md` §3 for the full module-by-module breakdown with responsibilities.

Local, hardware-free testing: `python3 tools/preview_render.py --screen <combined|debug|daytime|sleep|boot>` renders any of the local screens to a PNG (can't preview `ha_screen`, which needs a live HA fetch).

---

## Known Issues / Notes
- The `lib/waveshare_epd/` directory contains drivers for all Waveshare models. Only `epd7in5b_V2.py` is used. The others are kept for reference.
- `.so` compiled binary files (ARM) are gitignored — they only work on the Pi and are installed via apt.
- The web config panel (`web_config.py`) runs on port 5000, deployed as its own systemd unit: `sudo cp systemd/web_config.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now web_config`.
- `web_config.py` refuses to start unless `WEB_CONFIG_SECRET_KEY` and `WEB_CONFIG_PASSWORD_HASH` are set to real (non-placeholder) values in `.env` — see `.env.example` for the generation commands.
- The web UI's "Restart Service" button (`/api/restart`) needs a one-time passwordless-sudo entry on the Pi: `sudo cp systemd/bus_display_restart.sudoers.example /etc/sudoers.d/bus_display_restart && sudo chmod 440 /etc/sudoers.d/bus_display_restart && sudo visudo -c`.
- Secrets-at-rest: `app/.encryption_key` (gitignored, auto-generated on first run) encrypts password-type `.env` values saved through the web UI. Back this file up — losing it makes previously-encrypted secrets unrecoverable and they'd need to be re-entered.
- `.env` files don't support inline `#` comments after a value (e.g. `FORCE_SCREEN=# bus_train_screen` sets the literal string `"# bus_train_screen"`, not "unset"). Use `FORCE_SCREEN=` or comment out the whole line.
- `tests/` is harmless to leave deployed on the Pi (no runtime imports, no extra dependencies), but can optionally be excluded from the checked-out working tree via `git sparse-checkout` — see `How-to.md` step 2. A plain `rm -rf tests/` won't stick across a future `git pull`.
- See `todo.md` for everything planned but not yet built (placeholder `daytime_screen` content, `work_day`/`off_day` distinction, weather/calendar fallbacks for non-HA users, a pluggable screen architecture, etc.).
