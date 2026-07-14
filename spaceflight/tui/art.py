"""ASCII art, big digits, starfield, and rocket animations."""

from __future__ import annotations

import math
import random

# ── Big 3-row digits (blocky, btop-ish) ─────────────────────────
_DIGITS = {
    "0": ["████", "█  █", "█  █", "█  █", "████"],
    "1": [" ██ ", "███ ", " ██ ", " ██ ", "████"],
    "2": ["████", "   █", "████", "█   ", "████"],
    "3": ["████", "   █", "████", "   █", "████"],
    "4": ["█  █", "█  █", "████", "   █", "   █"],
    "5": ["████", "█   ", "████", "   █", "████"],
    "6": ["████", "█   ", "████", "█  █", "████"],
    "7": ["████", "   █", "  █ ", " █  ", " █  "],
    "8": ["████", "█  █", "████", "█  █", "████"],
    "9": ["████", "█  █", "████", "   █", "████"],
    ":": ["    ", " ██ ", "    ", " ██ ", "    "],
    "-": ["    ", "    ", "████", "    ", "    "],
    "+": ["    ", " ██ ", "████", " ██ ", "    "],
    "T": ["████", " ██ ", " ██ ", " ██ ", " ██ "],
    " ": ["    ", "    ", "    ", "    ", "    "],
    "d": ["    ", " ███", "█  █", "█  █", " ███"],
    "h": ["█   ", "█   ", "███ ", "█  █", "█  █"],
    "m": ["    ", "████", "█ ██", "█  █", "█  █"],
    "s": ["    ", " ███", "██  ", "  ██", "███ "],
    "L": ["█   ", "█   ", "█   ", "█   ", "████"],
    "I": ["███ ", " █  ", " █  ", " █  ", "███ "],
    "F": ["████", "█   ", "███ ", "█   ", "█   "],
    "O": ["████", "█  █", "█  █", "█  █", "████"],
    "V": ["█  █", "█  █", "█  █", " ██ ", " ██ "],
    "E": ["████", "█   ", "███ ", "█   ", "████"],
    "S": ["████", "█   ", "████", "   █", "████"],
    "U": ["█  █", "█  █", "█  █", "█  █", "████"],
    "C": ["████", "█   ", "█   ", "█   ", "████"],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █"],
    "P": ["████", "█  █", "████", "█   ", "█   "],
    "A": ["████", "█  █", "████", "█  █", "█  █"],
    "N": ["█  █", "██ █", "█ ██", "█  █", "█  █"],
    "G": ["████", "█   ", "█ ██", "█  █", "████"],
    "Y": ["█  █", "█  █", " ██ ", " ██ ", " ██ "],
    "X": ["█  █", " ██ ", " ██ ", " ██ ", "█  █"],
    "?": ["████", "   █", " ██ ", "    ", " ██ "],
}

DIGIT_H = 5
DIGIT_W = 5  # glyph + gap


def render_big(text: str) -> list[str]:
    """Render text as list of 5 rows of block digits."""
    rows = [""] * DIGIT_H
    for ch in text:
        glyph = _DIGITS.get(ch, _DIGITS.get(ch.upper(), _DIGITS["?"]))
        for i in range(DIGIT_H):
            rows[i] += glyph[i] + " "
    return rows


def compact_countdown_parts(secs: float | None, status: str = "") -> str:
    """String for big digit display, e.g. 'T-01:23:45' or 'LIFTOFF'."""
    if secs is None:
        return "NET TBD"
    abb = (status or "").lower()
    if abb in ("success",) and secs < 0:
        return "SUCCESS"
    if "fail" in abb and secs < 0:
        return "FAILURE"
    if secs < 0:
        s = int(-secs)
        if s < 120:
            return "LIFTOFF"
        # T+
        return "T+" + _hms(s)
    return "T-" + _hms(int(secs))


def _hms(s: int) -> str:
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}"
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ── Rockets ─────────────────────────────────────────────────────

ROCKET_SMALL = [
    "  /\\  ",
    " |==| ",
    " |  | ",
    " |  | ",
    " |==| ",
    "/_||_\\",
]

ROCKET_TALL = [
    "    /\\    ",
    "   /  \\   ",
    "  | ** |  ",
    "  |    |  ",
    "  |====|  ",
    "  |    |  ",
    "  |    |  ",
    "  |====|  ",
    " /|    |\\ ",
    "/_|_||_|_\\",
]

STARSHIP = [
    "     /\\     ",
    "    /  \\    ",
    "   | [] |   ",
    "   |    |   ",
    "   |====|   ",
    "   |    |   ",
    "   |    |   ",
    "   |    |   ",
    "   |====|   ",
    "  /|    |\\  ",
    " / |    | \\ ",
    "/__|_||_|__\\",
]

FLAMES = [
    ["  )(  ", "  )(  ", "   *  "],
    ["  )(  ", " )  ( ", "  **  "],
    [" )  ( ", "  )(  ", " **** "],
    ["  )(  ", " (  ) ", "  **  "],
]


def rocket_for(name: str) -> list[str]:
    n = (name or "").lower()
    if "starship" in n or "super heavy" in n:
        return STARSHIP
    if "falcon" in n or "f9" in n:
        return ROCKET_TALL
    return ROCKET_SMALL


def flame_frame(tick: int) -> list[str]:
    return FLAMES[tick % len(FLAMES)]


# ── Starfield ───────────────────────────────────────────────────

class Starfield:
    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.stars: list[tuple[float, float, int]] = []  # x, y frac, phase
        self._w = 0
        self._h = 0

    def resize(self, w: int, h: int) -> None:
        if w == self._w and h == self._h:
            return
        self._w, self._h = w, h
        n = max(8, (w * h) // 40)
        self.stars = [
            (self.rng.random(), self.rng.random(), self.rng.randint(0, 7))
            for _ in range(n)
        ]

    def cells(self, tick: int) -> list[tuple[int, int, str]]:
        """Return (y, x, char) for twinkling stars."""
        chars = "·.+*✦·.+*"
        out = []
        for xf, yf, phase in self.stars:
            x = int(xf * max(1, self._w - 1))
            y = int(yf * max(1, self._h - 1))
            ch = chars[(phase + tick // 2) % len(chars)]
            # only twinkle some
            if (phase + tick) % 5 == 0:
                ch = " "
            out.append((y, x, ch))
        return out


# ── Progress / bars ─────────────────────────────────────────────

def progress_bar(frac: float, width: int, fill: str = "█", empty: str = "░") -> str:
    width = max(4, width)
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return fill * n + empty * (width - n)


def sparkline(values: list[float], width: int) -> str:
    if not values or width < 1:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    span = (mx - mn) or 1.0
    # resample
    out = []
    for i in range(width):
        idx = int(i * (len(values) - 1) / max(1, width - 1))
        v = values[idx]
        bi = int((v - mn) / span * (len(blocks) - 1))
        out.append(blocks[bi])
    return "".join(out)


def spinner(tick: int) -> str:
    return "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[tick % 10]


def pulse_prefix(tick: int, live: bool = False) -> str:
    if live:
        return "●" if (tick // 2) % 2 == 0 else "○"
    frames = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
    return frames[tick % len(frames)]


def banner_spaceflight(tick: int = 0) -> str:
    frames = [
        "✦ SPACEFLIGHT ✦",
        "✧ SPACEFLIGHT ✧",
        "⋆ SPACEFLIGHT ⋆",
        "✧ SPACEFLIGHT ✧",
    ]
    return frames[tick % len(frames)]


def mission_control_deco(width: int, tick: int) -> str:
    edge = "═" * max(0, (width - 20) // 2)
    mid = f"⟨ MC-{tick % 1000:03d} ⟩"
    s = edge + mid + edge
    return s[:width]
