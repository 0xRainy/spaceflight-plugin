# Spaceflight

Flashy terminal **mission control** for rocket launches — btop energy, live T-countdowns, ASCII flight paths, Waybar module, and desktop notifications.

Data comes from public launch trackers (no AI, no account):

| Source | What it provides |
|--------|------------------|
| [Launch Library 2](https://thespacedevs.com/llapi) | Schedule, NET, status, vehicle/booster, payload, pad, streams, updates, timeline when present |
| [Rocket Launch Live](https://www.rocketlaunch.live/api) (free next-5) | Weather for near-term launches |
| [SpaceX CMS](https://content.spacex.com) (`api/spacex-website/missions/…`) | Official countdown + flight-test timeline, mission copy, trajectory infographic (same data as spacex.com/launches/…) |

Free LL2 rate limit is ~**15 requests/hour**. Spaceflight caches aggressively and only hits the network about **every 5 minutes**.

## Git (local)

This project is a **local git repo** so you don’t lose good versions:

```bash
cd ~/projects/spaceflight
git log --oneline
git tag                 # v0.1.0 = first solid build, v0.2.0 = flashy UI
git checkout v0.1.0     # time travel if needed
```

## Quick start

```bash
spaceflight                 # mission-control TUI
spaceflight list
spaceflight refresh         # force network pull (rate-limited)
spaceflight status
```

Daemon (already enabled if you ran install):

```bash
systemctl --user status spaceflight
```

## TUI — keys

| Key | Action |
|-----|--------|
| `j` / `k` or ↑/↓ | Move in launch queue **or** scroll detail |
| `Tab` | Focus queue ↔ mission-control panel |
| **`←` / `→` or `h` / `l`** | **Switch detail tabs** (when detail focused) |
| **`t`** | Next detail tab (works anytime) |
| **`1`–`6`** | Jump to tab |
| `[` / `]` | Previous / next tab |
| `f` | Cycle filter (ALL · GO · HOLD · LIVE · SpX) |
| `o` | Open primary livestream |
| `i` | Open best info link |
| `c` | Copy stream URL (`wl-copy`) |
| `r` | Force data refresh |
| `Esc` / Backspace | Back to launch queue |
| `q` | Quit |

### Detail tabs

1. **OVERVIEW** — big live countdown, rocket art, flames near T-0, progress bar, mission blurb  
2. **VEHICLE** — specs, record, booster serials / landings  
3. **PAYLOAD** — mission description & orbit  
4. **PATH** — ASCII projected trajectory + toy telemetry (ascent sketch)  
5. **MISSION** — SpaceX-style page: countdown events, flight stages, **infographic**, brief (`s` cycles TIMELINE / INFOGRAPHIC / BRIEF)  
6. **NEWS** — schedule changes / updates from LL2 editors  
7. **LIVE** — webcast links  

Countdowns recompute every frame (~10 fps animations, 1 Hz second digits). Network auto-refresh every **5 minutes**; cache reread every 15s if the daemon updated it.

### Stage notifications (desktop)

When a mission has a timeline (SpaceX CMS or LL2), the daemon notifies for **each stage** as wall-clock passes it — e.g. prop load, Max-Q, MECO, hot-staging, landing burn — not just T-1h / T-15m. Poll speeds up to **15s** inside the T-2h…T+2h window.

### Phone push (T-24h only) via ntfy

No extra system packages — uses HTTPS to [ntfy.sh](https://ntfy.sh) (or your own server).

1. Install the **ntfy** app on your phone (Android / iOS).
2. Pick a long random topic name (treat it like a password).
3. Subscribe to that topic in the app.
4. Configure Spaceflight:

```toml
# ~/.config/spaceflight/config.toml
[phone]
ntfy_topic = "your-long-random-topic-here"
ntfy_server = "https://ntfy.sh"
# ntfy_token = ""   # only if you use access control
t24h_only = true
```

Or: `export SPACEFLIGHT_NTFY_TOPIC=your-long-random-topic-here`

5. Test: `spaceflight notify-test --phone`

At **T-24h** the phone gets mission name, vehicle, location, local + UTC T-0, and a watch/info link (tappable). Stage spam stays on the desktop only.

### MISSION tab scrolling

On **BRIEF** and **INFOGRAPHIC**, use **`j`/`k`** (or PgUp/PgDn) to scroll. Press **`s`** to cycle views (auto-focuses the detail pane). Long briefs show a `j/k scroll` HUD.

## Waybar

Module runs **every 1 second** but only reads the local cache — **no API hammering**. Countdown text uses `T-HH:MM:SS` so it ticks live.

```jsonc
"custom/spaceflight": {
  "return-type": "json",
  "exec": "~/.config/waybar/scripts/spaceflight-waybar",
  "interval": 1,
  "tooltip": true,
  "on-click": "xdg-terminal-exec -e spaceflight",
  "on-click-right": "spaceflight refresh",
  "format": "{}"
}
```

Hover tooltip lists upcoming launches. Left-click opens the TUI.

## Notifications

User service `spaceflight.service`:

- Refresh network data ~every **5 minutes**
- Poll countdowns every minute for notify thresholds: **T-24h, T-6h, T-1h, T-15m, T-5m**, plus **webcast live**

## Cache paths

| Path | Purpose |
|------|---------|
| `~/.cache/spaceflight/launches.json` | Shared launch cache |
| `~/.cache/spaceflight/waybar.json` | Last waybar payload |
| `~/.local/state/spaceflight/notified.json` | Notification dedupe |
| `~/.local/state/spaceflight/daemon.log` | Daemon log |

## Project layout

```
projects/spaceflight/
├── spaceflight/
│   ├── api/           # LL2 + RocketLaunch.Live
│   ├── tui/
│   │   ├── app.py     # main mission-control UI
│   │   ├── art.py     # big digits, rockets, starfield
│   │   └── flightpath.py  # ASCII trajectory
│   ├── daemon.py
│   ├── waybar.py
│   └── …
├── scripts/
└── systemd/spaceflight.service
```

## Notes

- Flight PATH tab is a **fun stylized sketch** (gravity-turn style), not Flight Club guidance.
- Livestream URLs often appear only near launch; NEWS tab tracks NET slips as LL2 posts them.
- Be kind to free APIs — prefer the 5‑minute cadence over spamming `refresh`.
