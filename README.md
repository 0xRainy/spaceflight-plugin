# Spaceflight

Terminal rocket launch tracker with a **btop-style TUI**, background notifications, and a **Waybar** hover module.

Data comes from public launch trackers (no AI, no account required):

| Source | What it provides |
|--------|------------------|
| [Launch Library 2](https://thespacedevs.com/llapi) (The Space Devs) | Schedule, NET windows, status, vehicle/booster stats, payload, pad, livestream URLs, schedule-change updates |
| [Rocket Launch Live](https://www.rocketlaunch.live/api) (free next-5) | Weather summary for near-term launches |

Free LL2 rate limit is roughly **15 requests/hour**. Spaceflight caches aggressively and shares one cache across the TUI, daemon, and Waybar.

## Requirements

Already available on this system:

- Python 3 + `python-requests` + `python-rich`
- `notify-send` (mako)
- Waybar / systemd user session

No extra packages required. Optional: `wl-copy` for clipboard (`c` in the TUI).

## Quick start

```bash
cd ~/projects/spaceflight
./scripts/install.sh          # symlink CLI, enable daemon, seed cache
spaceflight                   # open TUI
spaceflight list              # text list
spaceflight refresh           # force network pull
```

## Commands

| Command | Description |
|---------|-------------|
| `spaceflight` / `spaceflight tui` | Interactive btop-style monitor |
| `spaceflight list [--json]` | Print upcoming launches |
| `spaceflight show <query>` | Detail for one launch |
| `spaceflight refresh` | Fetch from LL2 + weather |
| `spaceflight daemon` | Foreground background worker |
| `spaceflight daemon --once` | One refresh + notify pass |
| `spaceflight waybar` | JSON line for Waybar |
| `spaceflight notify-test` | Test desktop notification |
| `spaceflight status` | Paths / daemon state |

## TUI keybinds

| Key | Action |
|-----|--------|
| `j` / `k` or arrows | Navigate list / scroll detail |
| `Tab` | Focus list ↔ detail |
| `[` / `]` or `1`–`5` | Detail tabs (Overview / Vehicle / Payload / Updates / Streams) |
| `f` | Cycle filter (ALL · GO · HOLD · LIVE · SpX) |
| `o` | Open primary livestream |
| `i` | Open best external info link |
| `c` | Copy stream URL (`wl-copy`) |
| `r` | Force refresh |
| `q` | Quit |

## Notifications

The user systemd service `spaceflight.service` polls once a minute, refreshes the cache about every 5+ minutes, and fires desktop notifications at:

- **T-24h**, **T-6h**, **T-1h**, **T-15m**, **T-5m**
- When a launch is marked **webcast live**

Bodies include mission name, NET (local time), pad, and a livestream URL when known.

```bash
systemctl --user status spaceflight
journalctl --user -u spaceflight -f
# or app log:
tail -f ~/.local/state/spaceflight/daemon.log
```

## Waybar

Install adds `~/.config/waybar/scripts/spaceflight-waybar`. Wire it into `~/.config/waybar/config.jsonc`:

```jsonc
"modules-center": [ "clock", "custom/spaceflight", ... ],

"custom/spaceflight": {
  "return-type": "json",
  "exec": "~/.config/waybar/scripts/spaceflight-waybar",
  "interval": 30,
  "tooltip": true,
  "on-click": "xdg-terminal-exec -e spaceflight",
  "on-click-right": "spaceflight refresh",
  "format": "{}"
}
```

Tooltip lists the next launches with status, countdown, and stream markers. Left-click opens the TUI.

Restart: `omarchy restart waybar`

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
├── spaceflight/          # Python package
│   ├── api/              # LL2 + RocketLaunch.Live clients
│   ├── tui/              # curses TUI
│   ├── daemon.py
│   ├── waybar.py
│   ├── notify.py
│   └── cli.py
├── scripts/
│   ├── spaceflight
│   ├── spaceflight-waybar
│   └── install.sh
└── systemd/spaceflight.service
```

## Notes

- LL2 “upcoming” can briefly include just-completed flights; the TUI shows status (Success / Failure) and countdown (`T+…`).
- Livestream URLs often appear only near launch; Updates tab tracks NET slips and webcast posts as LL2 editors publish them.
- Be kind to the free APIs — prefer the daemon’s schedule over hammering `refresh`.
