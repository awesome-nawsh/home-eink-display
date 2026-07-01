# home-eink-display — Claude Code Context

## What This Is
A Raspberry Pi e-ink display that shows Singapore bus arrival times, MRT disruption alerts, and a Home Assistant dashboard screenshot during off-hours. Adapted from [awesomelionel's project](https://github.com/awesomelionel/singapore-bus-timing-edisplay).

**Current version:** v13.0  
**Status:** Production, running as a systemd service on a Raspberry Pi Zero W

Setting this up from scratch? See [How-to.md](How-to.md) for the full step-by-step guide.

---

## Hardware
- Raspberry Pi Zero W (user: `seanj`, home: `/home/seanj/`)
- Waveshare 7.5" e-ink display, B/W/R — driver: `epd7in5b_V2`
- Connected via GPIO HAT (no soldering)
- Pi path: `/home/seanj/singapore-bus-timing-edisplay/`

---

## Directory Structure

```
home-eink-display/
├── app/
│   ├── main.py          # Main application (~1580 lines). Entry point.
│   └── web_config.py    # Flask web UI to edit .env without SSH (port 5000)
├── lib/
│   └── waveshare_epd/   # Waveshare e-ink driver library
│       ├── epd7in5b_V2.py   ← THIS is the active driver
│       ├── epdconfig.py
│       └── (many other model drivers — not used)
├── pic/                 # Fonts loaded by PIL at runtime
│   ├── AtkinsonHyperlegibleNext-Regular.otf  ← primary font
│   ├── AtkinsonHyperlegibleNext-Bold.otf     ← bold variant
│   └── materialdesignicons-webfont.ttf       ← MDI icon font
├── systemd/
│   └── bus_display.service   # Deployed to /etc/systemd/system/ on Pi
├── images/              # Photos of the physical display (docs only)
├── .env                 # NOT in git — your real secrets
├── .env.example         # Template — commit this
├── .gitignore
├── requirements.txt
├── README.md
├── CHANGELOG.md
└── CLAUDE.md            # This file
```

---

## Configuration
All configuration is via a `.env` file in the project root (loaded by `python-dotenv`).  
See `.env.example` for all available variables with descriptions.

Key variables:
- `API_KEY` — LTA DataMall API key (required)
- `BUS_STOP_CODE_A` — 5-digit bus stop code
- `HOME_ASSISTANT_API_URL` / `HOME_ASSISTANT_TOKEN` — HA integration
- `SHOW_JOURNEY_TIME` — enable/disable commute time estimates
- `WAKE_HOUR` / `SLEEP_HOUR` — display active hours (default 7am–10pm)
- `MQTT_ENABLED` — allow HA to trigger display refreshes

---

## Deploy Workflow (Mac → Pi)

```bash
# 1. Make changes locally and commit
git add .
git commit -m "your message"
git push

# 2. SSH to Pi and pull
ssh seanj@<pi-ip>
cd /home/seanj/singapore-bus-timing-edisplay
git pull

# 3. Restart the service
sudo systemctl restart bus_display

# 4. Check it's running
sudo systemctl status bus_display
journalctl -u bus_display -f   # live logs
```

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

The service file lives at `/etc/systemd/system/bus_display.service`.  
After editing the service file on the Pi, run `sudo systemctl daemon-reload`.

---

## Pi Dependencies (apt, not pip)

```bash
sudo apt-get install python3-pigpio pigpiod
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

Python packages (pip):
```bash
pip3 install -r requirements.txt
```

---

## Key Code Sections in main.py

| Lines | What |
|-------|------|
| 1–130 | Imports, env var loading, all constants |
| 337–360 | Font helpers (`get_font`, `get_font_bold`, `get_icon_font`) |
| ~400–600 | API fetch functions (bus, train, weather, routing) |
| ~700–800 | `SystemHealth` class — tracks API success/failure rates |
| ~900–1100 | Draw functions (`draw_bus_section`, `draw_weather`, etc.) |
| ~1100–1300 | `display_combined_view()` — main render loop |
| ~1400–1579 | Entry point, sleep logic, watchdog, signal handling |

---

## Known Issues / Notes
- `bus_display.service` had a typo: `Restart=alwayson-falure` — fixed to `Restart=on-failure` in this repo. Re-deploy the service file to the Pi.
- The `lib/waveshare_epd/` directory contains drivers for all Waveshare models. Only `epd7in5b_V2.py` is used. The others are kept for reference.
- `.so` compiled binary files (ARM) are gitignored — they only work on the Pi and are installed via apt.
- The web config panel (`web_config.py`) runs on port 5000. Deploy it as its own persistent service: `sudo cp systemd/web_config.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now web_config`.
- `web_config.py` refuses to start unless `WEB_CONFIG_SECRET_KEY` and `WEB_CONFIG_PASSWORD_HASH` are set to real (non-placeholder) values in `.env` — see `.env.example` for the generation commands.
- The web UI's "Restart Service" button (`/api/restart`) needs a one-time passwordless-sudo entry on the Pi: `sudo cp systemd/bus_display_restart.sudoers.example /etc/sudoers.d/bus_display_restart && sudo chmod 440 /etc/sudoers.d/bus_display_restart && sudo visudo -c`.
- Secrets-at-rest: `app/.encryption_key` (gitignored, auto-generated on first run) encrypts password-type `.env` values saved through the web UI. Back this file up — losing it makes previously-encrypted secrets unrecoverable and they'd need to be re-entered.
