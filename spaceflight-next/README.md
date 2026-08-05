# Spaceflight Next

**A real redesign** of the mission-control TUI — not a reskin of the old layout.

Matches the GitHub landing page preview:

```
╭ queue ────────────╮  ╭ mission ────────────────────────────╮
│┃ ◆ BlueBird    GO │  │          NET COUNTDOWN              │
│  · Starlink    GO │  │     ████  solid block digits  ████   │
│  ○ NROL-95    TBC │  │     BlueBird 11-13                  │
╰───────────────────╯  │  ◆ RANGE CLEAR  ● STREAM  ☁ GO 80% │
                       │  Next · Prop load · T−00h:35m       │
                       ╰─────────────────────────────────────╯
[1 HOME]  2 PATH  3 DATA  4 EVENTS  5 WATCH
```

## Full power, new chrome

| Feature | How |
|---------|-----|
| Live LL2 data | same `spaceflight` cache + refresh |
| PATH infographic | Kitty/Ghostty graphics (SpaceX CMS) |
| HOME stream + radar | dual panes when live / hold / scrub |
| DATA / EVENTS / WATCH | full original content builders |
| Filters, open, copy, test flight, LL2 popup | yes |

## Run

```bash
./scripts/spaceflight-next
```

## Keys

| Key | Action |
|-----|--------|
| `j`/`k` | Queue (HOME) or scroll / stream pick |
| `1`–`5` | Tabs |
| `f` | Filter |
| `o` / `i` / `c` | Stream / info / copy |
| `r` | Refresh |
| `Ctrl+D` | LL2 log |
| `Ctrl+T` | Test flight |
| `q` | Quit |

## Power of Ten

Same mechanical bar as the main package:

```bash
PYTHONPATH=spaceflight-next:. python3 tools/check_p10.py   # 0 findings
```

Modules stay small (`theme`, `draw`, `sky`, `countdown`, `home`, `panels`, `keys`, `app`):
functions ≤ 60 lines, ≥ 2 `c_assert`s, bounded loops.
