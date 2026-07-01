
# mySGbusAuntie

***Disclaimer:*** this is my first project on this, I am by no means an expert and just do these fun projects on the side to challenge myself.

I've forked and adapted the code from [awesomelionel's project](https://github.com/awesomelionel/singapore-bus-timing-edisplay) to create my own version of the SGBusAuntie.

This project was a fun project that I keep tweaking but what I was trying to do was

1) In the mornings when my kids go to school they (like to original author of the code) need to know the buses and bus arrival times at the nearest bus stops where we live.
2) In addition because they take the train (subway / MRT) after the bus they need to know if there any distruptions along the route.
3) Once they have gone I dont need the display to show the bus times any more but rather some useful information, so I chose to display a dashboard from my homeassistant instance that shows weather for today, the 5 day outlook and also the calendar entries for today and the next day

#### Some pictures:
Bus Stop and Train display with weather

<img src="images/IMG_2594.jpeg" height=400 width=300>

Alternate display from HomeAssistant once not in bus monitoring period

<img src="images/IMG_2601.jpeg" height=400 width=300>

---

### Hardware 
(use the available sources in your country, for me it was a combination of amazon, lazada, shopee, cytron, aliexpress)
  1) Raspberry Pi Zero W (link later) with GPIO header pins (you can use a Pi Zero 2 W too!)
  2) Waveshare 7.5inch e-ink B/W/R (link later)
  3) HAT for Waveshare with GPIO interface for RPi (this makes it easier to install without soldering)
  4) IKEA picture frame (link later)
  5) Access to a 3D printer to print the parts needed (frame for display to sit on, internal frame and backing to hold frame down and for pi to sit on - link to follow for my STLs) 
  6) Power supply and cable for RPi in 1) above

Here is the mount using the IKEA picture frame

<img src="images/IMG_2581.jpeg" height=400 width=300>

### Software
  1) All written in Python, using the Waveshare e-ink libraries plus the LTA DataMall, OneMap/Google, and Home Assistant APIs
  2) You will need an API key to access the data from the LTA via their DataMall, and (optionally) an API key from OneMap or Google Maps for journey-time estimates
  3) A running Home Assistant instance is optional but unlocks weather, day-type-aware scheduling (school day vs. work day vs. off day), and the dashboard-screenshot screen
  4) If you want the HA dashboard screenshot screen, install the Graphite Theme and Puppeteer add-on on your Home Assistant instance

### Installation

**Full step-by-step instructions are in [How-to.md](How-to.md)** — clone, install dependencies, configure `.env` and the screen schedule, deploy both systemd services (the display + the web config panel), and verify it's working. That's now the canonical setup guide; the rest of this README is the project's backstory and roadmap.

Short version:
1) Clone this repo onto your Pi
2) Install dependencies (`pigpio` via apt, everything else via `pip3 install -r requirements.txt --break-system-packages`)
3) Copy `.env.example` → `.env` and fill in your LTA DataMall API key, bus stop code, and (optionally) Home Assistant/routing details
4) Deploy `systemd/bus_display.service` (the display) and `systemd/web_config.service` (a browser-based settings panel at `http://<pi-ip>:5000`, no SSH needed for day-to-day config changes)
5) If you want the HA dashboard screen, set up your dashboard and the Puppeteer add-on per its own GitHub instructions

### Disclaimers
1) This was a weekend project and i am not a professional software engineer !
2) Yes there is optimisation to this code - happy for suggestions etc but will be updating as and when I get the time

---

### What It Does Now

The display cycles through four screens on independent schedules (configurable via the web UI or `app/schedule_config.json`):
- **Bus/train view** — live bus arrivals, MRT disruption alerts, weather, and journey-time estimates. Only shows on school days (resolved automatically from Home Assistant, if configured).
- **Sleep screen** — a minimal overnight screen, no network calls, lowest power draw.
- **Daytime placeholder** — shown on non-school days for now (real content is still on the roadmap, see below).
- **HA dashboard screen** — an optional screenshot of a Home Assistant dashboard (weather, calendar, etc.), shown in any schedule gap the other three don't claim.

A password-protected web config panel (`http://<pi-ip>:5000`) lets you edit settings and the schedule from a browser, with live conflict-checking and no SSH required for most changes.

### Future Enhancement Ideas

Potential features for future versions (see `todo.md` in this repo for the fuller, actively-maintained list):
- [ ] Multiple bus stops with tabs + button to switch tabs
- [ ] Add a button and LED for refresh and reboot
- [ ] Add Air quality data next to the weather
- [ ] Add Calendar events from HA (only the days events), plus a direct calendar (`.ics`) integration for anyone not running Home Assistant
- [ ] Weather fallback to a public API when Home Assistant isn't available
- [ ] Real content for the daytime placeholder screen (currently just says "Day time screen")
- [ ] A more modular/pluggable screen architecture (rolling screens, custom image slideshows, multiple HA dashboard targets)
- [✅] ~~Web interface for configuration~~ (Added in v14.0 — session auth, live schedule editor, one-click restart)
- [✅] ~~Commute time estimates~~ (Added in v13.0)
- [✅] ~~Accessibility-optimized typography~~ (Added in v12.0)
- [✅] ~~Bold emphasis for key information~~ (Added in v12.0)

---

## Credits & Thanks

**Technologies Used:**
- Waveshare E-Ink Display (7.5" V2)
- Raspberry Pi Zero
- Python 3, Flask
- Material Design Icons v7.4.47
- Atkinson Hyperlegible Next Font (Braille Institute)
- Paho MQTT
- Home Assistant
- Singapore LTA DataMall API

-----

**Current Version: v14.0**  
**Status: Production Ready** ✅  

-----

### Getting Help / Contributing

- Setup issues: see [How-to.md](How-to.md)'s troubleshooting section first, then `journalctl -u bus_display -f` / `journalctl -u web_config -f` for live logs.
- Deeper questions about how something works: [architecture.md](architecture.md), [design.md](design.md), [specifications.md](specifications.md), and [screen_layout.md](screen_layout.md) cover structure, rationale, behavior, and exact pixel layout respectively.
- What's planned but not built yet: `todo.md`.
