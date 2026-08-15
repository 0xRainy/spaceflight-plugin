# Spaceflight

Flashy **mission control** for rocket launches — Omarchy Quattro bar plugin, terminal TUI, desktop alerts, and optional phone push via [ntfy](https://ntfy.sh).

**[Project site →](https://0xrainy.github.io/spaceflight-plugin/)** · live screenshots, Power of Ten, one-minute install.

Listed for **[Omarchy Quattro](https://omarchyplugins.com/)** as plugin id `0xrainy.spaceflight`. Click the bar pill for a mission card (queue, NET local/UTC, window, Now/Next stages). Right-click opens the TUI.

**Version 1.0.0** — Gerard Holzmann’s [**Power of Ten**](https://spinroot.com/gerard/pdf/P10.pdf) (NASA/JPL), adapted for Python. See [`docs/POWER_OF_TEN.md`](docs/POWER_OF_TEN.md).

```bash
PYTHONPATH=. python3 tools/check_p10.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## Install (Omarchy Quattro)

```bash
omarchy plugin add https://github.com/0xRainy/spaceflight-plugin
```

Omarchy asks **left / center / right**. Then **click the bar rocket** (`🚀  setup`) to finish:

1. Optional **background service** (live countdown + desktop alerts).
2. Optional **ntfy** phone alerts (free app; the topic is a secret).

After that, click the rocket for the mission card. Press **`s`** in the TUI to change settings later.

## Uninstall

```bash
omarchy plugin remove 0xrainy.spaceflight --yes
```

That also stops `spaceflight.service`, removes the CLI symlink, and **wipes local prefs** (bar look, ntfy topic, onboard flags, cache). Same if you remove it from the Omarchy menu. The next `omarchy plugin add` runs the full setup again.

## After install

| Command | What |
|---------|------|
| Click the bar rocket | Mission card (replaces hover tooltip) |
| Right-click the bar | Open TUI |
| Middle-click | `spaceflight refresh` |
| `spaceflight` | Mission-control TUI |
| `spaceflight setup` | ntfy phone wizard |
| `n` in TUI | Toggle stage notification spam |

Requirements: **Python 3.11+**, `requests`, `notify-send` (desktop alerts). Optional: Kitty/Ghostty for TUI images. Waybar still works via `scripts/spaceflight-waybar`.

### First-install onboarding (ntfy phone alerts)

`install.sh` runs an interactive wizard when you have a TTY:

```
════════════════════════════════════════════════════
  Spaceflight — first-time setup
════════════════════════════════════════════════════

  Desktop notifications & Waybar work without this.
  Phone push uses free ntfy (https://ntfy.sh).
  Your topic name is a secret — never commit it.

  [1] Generate a private topic for me  (recommended)
  [2] I already have an ntfy topic
  [3] Skip — desktop / Waybar only for now

Choice [1]:
```

**Path [1] — generate (recommended)**

1. Install the free **ntfy** app (Android / iOS / [ntfy.sh](https://ntfy.sh)).
2. Wizard prints a long random topic (treat it like a password).
3. In the app: **Subscribe** → paste that topic.
4. Press Enter, optional server/token tweaks, then a **test push**.
5. Settings saved to `~/.config/spaceflight/config.toml` (mode `0600`).

**Path [2]** — paste a topic you already use.  
**Path [3]** — skip; desktop + Waybar still work. Re-run anytime:

```bash
spaceflight setup              # wizard
spaceflight setup --status     # topic masked (never full secret)
spaceflight notify-test --phone
```

Non-interactive installs print a hint instead of the wizard.

> **Security:** `ntfy_topic` / `ntfy_token` must never be committed or pasted into issues.  
> See [SECURITY.md](SECURITY.md). The repo only ships empty `config.example.toml`.

## Quick start

```bash
spaceflight                 # mission-control TUI
spaceflight list
spaceflight refresh         # force network pull (rate-limited)
spaceflight status
spaceflight setup           # phone (ntfy) wizard
```

Daemon:

```bash
systemctl --user status spaceflight
```

## Data sources (no account)

| Source | What it provides |
|--------|------------------|
| [Launch Library 2](https://thespacedevs.com/llapi) | Schedule, NET, status, vehicle, pad, streams, timelines |
| [Rocket Launch Live](https://www.rocketlaunch.live/api) | Weather for near-term launches (free next-5) |
| [SpaceX CMS](https://content.spacex.com) | Official countdown / flight-test timelines, mission copy |

Free LL2 ≈ **15 requests/hour**. Spaceflight caches aggressively and uses a smart pull schedule around NET.

## TUI — keys

| Key | Action |
|-----|--------|
| `j` / `k` or ↑/↓ | Move in launch queue **or** scroll detail |
| `Tab` | Focus queue ↔ mission-control panel |
| **`←` / `→` or `h` / `l`** | **Switch detail tabs** (when detail focused) |
| **`t`** | Next detail tab |
| **`1`–`5`** | Jump to tab |
| `f` | Cycle filter (ALL · GO · HOLD · LIVE · SpX) |
| `o` | Open primary livestream |
| `i` | Open best info link |
| `c` | Copy stream URL (`wl-copy`) |
| `r` | Force data refresh |
| `Esc` / Backspace | Back to launch queue |
| `q` | Quit |

| Key | View | What you see |
|-----|------|----------------|
| `1` | **HOME** | Live T-countdown, stream + radar panes, status bus |
| `2` | **PATH** | Trajectory image (Kitty/Ghostty) + stage rail |
| `3` | **DATA** | Vehicle, boosters, payload, mission brief |
| `4` | **EVENTS** | Countdown + flight timeline + schedule updates |
| `5` | **WATCH** | Livestreams & mission page links |

### Notifications

| Channel | When |
|---------|------|
| **Desktop** | T-24h / T-1h / T-10m, webcast live, hold, scrub, stages |
| **Phone (ntfy)** | T-24h / T-1h / T-10m, scrub/failure (no stage spam) |

Configure phone with `spaceflight setup` (or env `SPACEFLIGHT_NTFY_TOPIC` — avoid exporting secrets into shell history when possible).

## Waybar

Module ticks from the **local cache** (daemon rewrites every second) — no API hammering.

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

Add `"custom/spaceflight"` to a `modules-*` array. Finished / DONE flights are never featured on the bar.

## Local paths

| Path | Purpose |
|------|---------|
| `~/.config/spaceflight/config.toml` | User settings (**secrets live here**) |
| `~/.cache/spaceflight/launches.json` | Launch cache |
| `~/.cache/spaceflight/waybar.json` | Waybar payload |
| `~/.local/state/spaceflight/` | Notify dedupe, onboard state, logs |

## Project layout

```
spaceflight-tui/
├── config.example.toml    # safe template (empty secrets)
├── spaceflight/
│   ├── api/               # LL2 + RLL + SpaceX CMS
│   ├── ui/                # mission-control TUI (public)
│   ├── tui/               # shared helpers + prior layout (reference)
│   ├── onboard.py         # first-install ntfy wizard
│   ├── daemon.py
│   ├── waybar.py
│   └── …
├── scripts/install.sh
├── systemd/spaceflight.service
├── tests/
└── docs/
```

## License

MIT — see [LICENSE](LICENSE).
