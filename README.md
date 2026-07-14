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
4. **PATH** — ASCII projected trajectory + toy telemetry (ascent sketch, not radar)  
5. **NEWS** — schedule changes / updates from LL2 editors  
6. **LIVE** — webcast links  

Countdowns recompute every frame (~10 fps animations, 1 Hz second digits). Network auto-refresh every **5 minutes**; cache reread every 15s if the daemon updated it.

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
