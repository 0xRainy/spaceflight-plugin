"""ASCII art, big digits, starfield, and rocket animations."""

from __future__ import annotations

import math
import random

from ..p10 import (
    MAX_ASCII_COLS,
    MAX_ASCII_ROWS,
    MAX_LOOP_DEFAULT,
    c_assert,
    take_at_most,
)

# ── Big digits — solid blocks, high contrast (readable at a glance) ─
_DIGITS = {
    "0": ["█████", "█   █", "█   █", "█   █", "█████"],
    "1": ["  ██ ", " ████", "  ██ ", "  ██ ", "██████"],
    "2": ["█████", "    █", "█████", "█    ", "█████"],
    "3": ["█████", "    █", " ███ ", "    █", "█████"],
    "4": ["█   █", "█   █", "█████", "    █", "    █"],
    "5": ["█████", "█    ", "█████", "    █", "█████"],
    "6": ["█████", "█    ", "█████", "█   █", "█████"],
    "7": ["█████", "    █", "   █ ", "  █  ", "  █  "],
    "8": ["█████", "█   █", "█████", "█   █", "█████"],
    "9": ["█████", "█   █", "█████", "    █", "█████"],
    ":": ["     ", "  ██ ", "     ", "  ██ ", "     "],
    "-": ["     ", "     ", "█████", "     ", "     "],
    "+": ["     ", "  █  ", "█████", "  █  ", "     "],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    " ": ["     ", "     ", "     ", "     ", "     "],
    "d": ["     ", " ███ ", "█  █ ", "█  █ ", " ████"],
    "h": ["█    ", "█    ", "███  ", "█  █ ", "█  █ "],
    "m": ["     ", "████ ", "█ ██ ", "█  █ ", "█  █ "],
    "s": ["     ", " ████", "██   ", "  ███", "████ "],
    "L": ["█    ", "█    ", "█    ", "█    ", "█████"],
    "I": ["████ ", "  █  ", "  █  ", "  █  ", "████ "],
    "F": ["█████", "█    ", "███  ", "█    ", "█    "],
    "O": ["█████", "█   █", "█   █", "█   █", "█████"],
    "V": ["█   █", "█   █", "█   █", " █ █ ", "  █  "],
    "E": ["█████", "█    ", "███  ", "█    ", "█████"],
    "S": ["█████", "█    ", "█████", "    █", "█████"],
    "U": ["█   █", "█   █", "█   █", "█   █", "█████"],
    "C": ["█████", "█    ", "█    ", "█    ", "█████"],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
    "P": ["█████", "█   █", "█████", "█    ", "█    "],
    "A": ["█████", "█   █", "█████", "█   █", "█   █"],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "G": ["█████", "█    ", "█  ██", "█   █", "█████"],
    "Y": ["█   █", "█   █", " █ █ ", "  █  ", "  █  "],
    "X": ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
    "?": ["█████", "    █", "  ██ ", "     ", "  █  "],
}

DIGIT_H = 5
DIGIT_W = 6  # glyph width + gap
_MAX_BIG_CHARS = 32


def render_big(text: str) -> list[str]:
    """Render text as list of 5 rows of block digits."""
    if not c_assert(text is not None, "text required"):
        return [""] * DIGIT_H
    if not c_assert(DIGIT_H > 0, "DIGIT_H positive"):
        return []
    rows = [""] * DIGIT_H
    for ch in str(text)[:_MAX_BIG_CHARS]:
        glyph = _DIGITS.get(ch, _DIGITS.get(ch.upper(), _DIGITS["?"]))
        for i in range(DIGIT_H):
            rows[i] += glyph[i] + " "
    return rows


def compact_countdown_parts(secs: float | None, status: str = "") -> str:
    """String for big digit display, e.g. 'T-1d:20h:30m:20s' or 'LIFTOFF'."""
    if not c_assert(True, "compact_countdown entry"):
        return "NET TBD"
    if secs is None:
        return "NET TBD"
    abb = (status or "").lower()
    if not c_assert(isinstance(abb, str), "status str"):
        return "NET TBD"
    if abb in ("success",) and secs < 0:
        return "SUCCESS"
    if "fail" in abb and secs < 0:
        return "FAILURE"
    if secs < 0:
        s = int(-secs)
        if s < 120:
            return "LIFTOFF"
        return "T+" + _dhms(s)
    return "T-" + _dhms(int(secs))


def _dhms(s: int) -> str:
    """Match models._fmt_duration: omit 0d / 0h, always m+s."""
    if not c_assert(isinstance(s, int), "s int"):
        return "00m:00s"
    if not c_assert(s >= 0, "s non-negative"):
        s = abs(int(s))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    parts: list[str] = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h:02d}h")
    parts.append(f"{m:02d}m")
    parts.append(f"{sec:02d}s")
    return ":".join(parts)


def unit_parts(secs: float | None) -> tuple[str, str, str, str]:
    """Zero-padded unit strings for DAYS/HRS/MIN/SEC cards."""
    if not c_assert(True, "unit_parts entry"):
        return ("--", "--", "--", "--")
    if secs is None:
        return ("--", "--", "--", "--")
    if not c_assert(math.isfinite(float(secs)), "secs finite"):
        return ("--", "--", "--", "--")
    s = int(abs(secs))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    return (f"{d:02d}", f"{h:02d}", f"{m:02d}", f"{sec:02d}")


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
    if not c_assert(name is not None, "name required"):
        return list(ROCKET_SMALL)
    n = (name or "").lower()
    if not c_assert(isinstance(n, str), "name str"):
        return list(ROCKET_SMALL)
    if "starship" in n or "super heavy" in n:
        return list(STARSHIP)
    if "falcon" in n or "f9" in n:
        return list(ROCKET_TALL)
    return list(ROCKET_SMALL)


def flame_frame(tick: int) -> list[str]:
    if not c_assert(isinstance(tick, int), "tick int"):
        return list(FLAMES[0])
    if not c_assert(len(FLAMES) > 0, "flames non-empty"):
        return []
    # Advance flame on the shared ~0.5s blink cadence
    return list(FLAMES[blink_phase(tick) % len(FLAMES)])


# ── Unified blink (~0.5s intervals @ frame_ms=80) ───────────────
# half-period ticks: 500ms / 80ms ≈ 6.25 → 6
BLINK_HALF_TICKS = 6


def blink_on(tick: int) -> bool:
    """True for ~0.5s, False for ~0.5s (shared UI flash cadence)."""
    if not c_assert(isinstance(tick, int), "tick int"):
        return True
    if not c_assert(BLINK_HALF_TICKS > 0, "half positive"):
        return True
    return ((tick // BLINK_HALF_TICKS) % 2) == 0


def blink_phase(tick: int) -> int:
    """Integer phase advancing every ~0.5s (for multi-frame art)."""
    if not c_assert(isinstance(tick, int), "tick int"):
        return 0
    if not c_assert(BLINK_HALF_TICKS > 0, "half positive"):
        return 0
    return tick // BLINK_HALF_TICKS


# ── Post-liftoff stage scenes (classic rocket ASCII, animated) ───
# Style: classic terminal launch timeline (line-drawn vehicle + plume).
# Generic ELV. 2 frames/stage via blink_phase (~0.5s).

_STAGE_LIFTOFF = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '             ( . )',
        '            (  :  )',
        '          . (  :  ) .',
        "         '.(  :::: ).'",
        '         " " " " " " "',
        '        ===============  PAD',
        '           ~~ LIFTOFF ~~',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '            (  .  )',
        '           (   :   )',
        '         . (   :   ) .',
        "        '.(  ::::: ).'",
        '        " " " " " " " "',
        '       =================  PAD',
        '          ~~ THROTTLE UP ~~',
    ],
]

_STAGE_MAXQ = [
    [
        '             _ . - . _',
        '           (   /  \\   )',
        '          (   | [] |   )',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '             ( . )',
        '            (  :  )',
        '            (  :  )',
        '           ( :::: )',
        '           == MAX-Q ==',
    ],
    [
        '            . _ - _ .',
        '          (    /  \\    )',
        '         (    | [] |    )',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '            (  .  )',
        '           (   :   )',
        '           (   :   )',
        '          ( ::::: )',
        '          == MAX-Q ==',
    ],
]

_STAGE_MECO = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '              * *',
        '',
        '             |====|',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '          MECO · STAGE SEP',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             *   *',
        '',
        '             |====|',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '          MECO · BOOSTER AWAY',
    ],
]

_STAGE_SES = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             \\ _ /',
        '              ( )',
        '             ( ~ )',
        '            (~~~~~)',
        '          UPPER BURN · GO',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             \\ _ /',
        '             (  )',
        '            ( ~~ )',
        '           (~~~~~~)',
        '         VACUUM IGNITION',
    ],
]

_STAGE_SECO = [
    [
        '        .  *     .    *     .',
        '           *   free fall  *',
        '      *         .      *     .',
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '           --- SECO ---',
        '          coast to orbit',
    ],
    [
        '      *    .    *     .    *',
        '         *  free fall  *',
        '           .      *       .',
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '           --- SECO ---',
        '         orbit insertion',
    ],
]

_STAGE_DEPLOY = [
    [
        '              |____|',
        '              |    |',
        '              |____|',
        '',
        '          [][]  [][]  [][]',
        '          [][]  [][]  [][]',
        '',
        '          PAYLOAD DEPLOY',
    ],
    [
        '              |____|',
        '              |    |',
        '              |____|',
        '',
        '        [][]    [][]    [][]',
        '        [][]    [][]    [][]',
        '',
        '        SEPARATION CONFIRM',
    ],
]

_STAGE_COMPLETE = [
    [
        '        .  *   .  *   .  *',
        '      *        ___        *',
        "         .   .'   '.   *",
        '            /  LEO  \\',
        '           |  *---*  |',
        '            \\  OK  /',
        "         *   '.___.'   *",
        '      .         *         .',
        '         ON ORBIT · SUCCESS',
    ],
    [
        '      *  .   *  .   *  .',
        '        *      ___     *',
        "           .'   '.  *",
        '          /  LEO  \\',
        '         |  *---*  |',
        '          \\  OK  /',
        "        *  '.___.'  *",
        '      .       *        *',
        '        MISSION COMPLETE',
    ],
]

_STAGE_ASCENT = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '             ( . )',
        '            (  :  )',
        '           (  :  )',
        '          POWERED FLIGHT',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             |====|',
        '             |    |',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '            (  .  )',
        '           (   :   )',
        '          (   :   )',
        '         GUIDANCE NOMINAL',
    ],
]

# SpaceX F9 / Starship timeline stages (from LL2 flight events)
_STAGE_STAGE_SEP = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '              * *',
        '',
        '             |====|',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '         STAGE SEPARATION',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |____|',
        '             *   *',
        '',
        '             |====|',
        '             |    |',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '         S1 · S2 SPLIT',
    ],
]

_STAGE_FAIRING = [
    [
        '          \\          /',
        '           \\        /',
        '            |  []  |',
        '            |  []  |',
        '           /   []   \\',
        '          /   |____| \\',
        '              |    |',
        '              |____|',
        '              \\ _ /',
        '               ( )',
        '              ( ~ )',
        '         FAIRING SEPARATION',
    ],
    [
        '        \\              /',
        '         \\            /',
        '            |  []  |',
        '            |  []  |',
        '           /   []   \\',
        '          /   |____| \\',
        '              |    |',
        '              |____|',
        '              \\ _ /',
        '              (  )',
        '             ( ~~ )',
        '        FAIRINGS JETTISON',
    ],
]

_STAGE_ENTRY_BURN = [
    [
        '            \\ | /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '           ( . )',
        '          (  :  )',
        '         ( ::::: )',
        '         ENTRY BURN',
    ],
    [
        '           \\  |  /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          (  .  )',
        '         (   :   )',
        '        ( ::::::: )',
        '        ENTRY BURN',
    ],
]

_STAGE_LANDING_BURN = [
    [
        '            \\ | /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          \\ /   \\ /',
        '           V     V',
        '            ( . )',
        '           (  :  )',
        '         LANDING BURN',
    ],
    [
        '           \\  |  /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          \\ /   \\ /',
        '           V     V',
        '           (  .  )',
        '          (   :   )',
        '        LANDING BURN',
    ],
]

_STAGE_LANDING = [
    [
        '            \\ | /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          \\ /   \\ /',
        '         __V_____V__',
        '        |===========|',
        '     ~~~~~~~~~~~~~~~~~~~',
        '         STAGE LANDING',
    ],
    [
        '            \\ | /',
        '            / _ \\',
        '           |     |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          \\ /   \\ /',
        '         __V_____V__',
        '        |===========|  LZ',
        '     ~~~~~~~~~~~~~~~~~~~',
        '          TOUCHDOWN!',
    ],
]

_STAGE_BOOSTBACK = [
    [
        '            /| |\\',
        '           |  =  |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '           ( . )',
        '          (  :  )',
        '         BOOSTBACK BURN',
    ],
    [
        '            /| |\\',
        '           |  =  |',
        '           |     |',
        '           |     |',
        '          /|     |\\',
        '         /_|_____|_\\',
        '          (  .  )',
        '         (   :   )',
        '        BOOSTBACK BURN',
    ],
]

_STAGE_HOT_STAGE = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |####|  <-- hot stage',
        '             |====|',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '             * * *',
        '          HOT-STAGING',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |####|',
        '              * *',
        '             |====|',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '          HOT-STAGING',
    ],
]

_STAGE_SHIP_ENTRY = [
    [
        '        .  *    .   *',
        '           /====\\',
        '          |  SS  |',
        '          |______|',
        '         /  ~~~~  \\',
        '        /  ~~~~~~  \\',
        '       ~~~~~~~~~~~~~~',
        '        SHIP ENTRY',
    ],
    [
        '      *   .   *    .',
        '           /====\\',
        '          |  SS  |',
        '          |______|',
        '         / ~~~~~~ \\',
        '        /~~~~~~~~~~\\',
        '       ~~~~~~~~~~~~~~~~',
        '       ATMOSPHERIC ENTRY',
    ],
]

_STAGE_SHIP_LANDING = [
    [
        '           /====\\',
        '          |  SS  |',
        '          |______|',
        '           \\  /',
        '            \\/',
        '            (.)',
        '           (::)',
        '        __|====|__',
        '       |__________|',
        '        SHIP LANDING',
    ],
    [
        '           /====\\',
        '          |  SS  |',
        '          |______|',
        '           \\  /',
        '            \\/',
        '           ( . )',
        '          ( ::: )',
        '        __|====|__',
        '       |__________|  TOWER',
        '       CATCH ATTEMPT',
    ],
]

# ── Pre-launch / countdown stages (SpaceX F9 + Starship timelines) ──

_STAGE_GO_PROP = [
    [
        '         .-----------.',
        '         |  POLL     |',
        '         | [GO] [NO] |',
        '         |  *  FIDO  |',
        '         \'-----------\'',
        '               |',
        '            [ LD ]',
        '         GO FOR PROP LOAD',
    ],
    [
        '         .-----------.',
        '         |  POLL     |',
        '         | [**GO**]  |',
        '         |  *  FIDO  |',
        '         \'-----------\'',
        '               |',
        '            [ LD ]',
        '         PROP LOAD CLEARED',
    ],
]

_STAGE_PROP_LOAD = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |~~~~|  LOX',
        '             |~~~~|  RP-1',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '         << TANKING >>',
        '         PROPELLANT LOAD',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |~~~~|  LOX',
        '             |~~~~|  CH4',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '         << TANKING >>',
        '          LOAD UNDERWAY',
    ],
]

_STAGE_PROP_COMPLETE = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |####|  FULL',
        '             |####|  FULL',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '         PROP LOAD COMPLETE',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |####|  OK',
        '             |####|  OK',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '          TANKS AT FLIGHT',
    ],
]

_STAGE_ENGINE_CHILL = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '            * * * *',
        '           frost  o',
        '         ENGINE CHILL',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |    |',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '           *  *  *  *',
        '          o  frost',
        '        CHILLING RAPTORS',
    ],
]

_STAGE_PRESSURIZE = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |====|  PSI',
        '             |####|  ^^^',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '         TANK PRESSURIZE',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |====|  PSI',
        '             |####|  ^^^^',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '        FLIGHT PRESSURE',
    ],
]

_STAGE_FINAL_CHECKS = [
    [
        '         .-----------------.',
        '         | FC  [====....]  |',
        '         | GNC [======..]  |',
        '         | RF  [====....]  |',
        '         | AV  [======..]  |',
        '         \'-----------------\'',
        '         FINAL PRELAUNCH',
    ],
    [
        '         .-----------------.',
        '         | FC  [========]  |',
        '         | GNC [========]  |',
        '         | RF  [========]  |',
        '         | AV  [========]  |',
        '         \'-----------------\'',
        '         CHECKS NOMINAL',
    ],
]

_STAGE_GO_LAUNCH = [
    [
        '         .-----------.',
        '         | LAUNCH    |',
        '         | DIRECTOR  |',
        '         |  [ GO ]   |',
        '         \'-----------\'',
        '              ||',
        '         ============',
        '         GO FOR LAUNCH',
    ],
    [
        '         .-----------.',
        '         | LAUNCH    |',
        '         | DIRECTOR  |',
        '         | [**GO**]  |',
        '         \'-----------\'',
        '              ||',
        '         ============',
        '          CLEARED T-0',
    ],
]

_STAGE_FLAME_DIVERTER = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '         ~~~~~~~~~~~~~~',
        '         ~~~~~~~~~~~~~~',
        '         FLAME DIVERTER',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |====|',
        '            /|    |\\',
        '           /_|____|_\\',
        '        ~~~~~~~~~~~~~~~~',
        '        ~~ WATER DELUGE ~~',
        '        DIVERTER ACTIVE',
    ],
]

_STAGE_IGNITION = [
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |====|',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '             ( . )',
        '            (  :  )',
        '         ENGINE STARTUP',
    ],
    [
        '               /\\',
        '              /  \\',
        '             | [] |',
        '             |____|',
        '             |====|',
        '             |    |',
        '            /|    |\\',
        '           /_|____|_\\',
        '            (  .  )',
        '           (   :   )',
        '         IGNITION SEQ',
    ],
]

_STAGE_HOLD = [
    [
        '         .-----------.',
        '         |  T- ##:## |',
        '         |  [HOLD]   |',
        '         |  FROZEN   |',
        '         \'-----------\'',
        '              ||',
        '         ============',
        '           ON HOLD',
    ],
    [
        '         .-----------.',
        '         |  T- ##:## |',
        '         | [*HOLD*]  |',
        '         |  FROZEN   |',
        '         \'-----------\'',
        '              ||',
        '         ============',
        '         COUNTDOWN HOLD',
    ],
]

_STAGE_KIND_ART: dict[str, list[list[str]]] = {
    # Flight
    "liftoff": _STAGE_LIFTOFF,
    "maxq": _STAGE_MAXQ,
    "meco": _STAGE_MECO,
    "stage_sep": _STAGE_STAGE_SEP,
    "ses": _STAGE_SES,
    "seco": _STAGE_SECO,
    "fairing": _STAGE_FAIRING,
    "entry_burn": _STAGE_ENTRY_BURN,
    "landing_burn": _STAGE_LANDING_BURN,
    "landing": _STAGE_LANDING,
    "boostback": _STAGE_BOOSTBACK,
    "hot_stage": _STAGE_HOT_STAGE,
    "ship_entry": _STAGE_SHIP_ENTRY,
    "ship_landing": _STAGE_SHIP_LANDING,
    "deploy": _STAGE_DEPLOY,
    "complete": _STAGE_COMPLETE,
    "ascent": _STAGE_ASCENT,
    # Pre-launch / countdown
    "go_prop": _STAGE_GO_PROP,
    "prop_load": _STAGE_PROP_LOAD,
    "prop_complete": _STAGE_PROP_COMPLETE,
    "engine_chill": _STAGE_ENGINE_CHILL,
    "pressurize": _STAGE_PRESSURIZE,
    "final_checks": _STAGE_FINAL_CHECKS,
    "go_launch": _STAGE_GO_LAUNCH,
    "flame_diverter": _STAGE_FLAME_DIVERTER,
    "ignition": _STAGE_IGNITION,
    "hold": _STAGE_HOLD,
}


def _kind_landingish(n: str) -> str | None:
    if not c_assert(isinstance(n, str), "n str"):
        return None
    if not c_assert(True is not False, "landingish"):
        return None
    if "landing burn" in n:
        if "starship" in n or ("ship" in n and "super heavy" not in n):
            return "ship_landing"
        return "landing_burn"
    if "landing flip" in n or "exciting landing" in n or "catch" in n:
        return "ship_landing"
    if "1st stage landing" in n or n.strip() in ("landing", "touchdown"):
        return "landing"
    if "landing" in n and "burn" not in n:
        if "starship" in n or ("ship" in n and "super heavy" not in n):
            return "ship_landing"
        return "landing"
    return None


def _kind_engineish(n: str) -> str | None:
    if not c_assert(isinstance(n, str), "n str"):
        return None
    if not c_assert(True is not False, "engineish"):
        return None
    # Pre-liftoff ignition / startup (before SES token match)
    if (
        "ignition sequence" in n
        or "startup sequence" in n
        or "engine startup" in n
        or n.strip() in ("startup", "ignition", "startup sequence")
    ):
        return "ignition"
    # Token-ish SES (avoid bare substring traps)
    if "ses-" in n or "ses " in n or "(ses" in n or "engine starts" in n:
        return "ses"
    if "relight" in n:
        return "ses"
    # "seco" is a substring of "second" — require token boundaries (seco-1, SECO, (SECO))
    if (
        "seco-" in n
        or "seco " in n
        or "seco)" in n
        or n.strip() == "seco"
        or "engine cutoff" in n
        or ("cutoff" in n and "meco" not in n)
    ):
        return "seco"
    return None


def _kind_prelaunch(n: str) -> str | None:
    """Map countdown / pad events → art keys."""
    if not c_assert(isinstance(n, str), "n str"):
        return None
    if not c_assert(True is not False, "prelaunch"):
        return None
    if "hold" in n:
        return "hold"
    if "flame diverter" in n or "water deluge" in n:
        return "flame_diverter"
    if "engine chill" in n or "begins engine chill" in n or "chill on booster" in n:
        return "engine_chill"
    if "pressurization" in n or "flight pressure" in n or "tank press" in n:
        return "pressurize"
    if (
        "prelaunch check" in n
        or "final prelaunch" in n
        or "flight computer" in n
        or "final prelaunch checks" in n
    ):
        return "final_checks"
    # Prop load complete before generic load / complete
    if "propellant load complete" in n or (
        "load complete" in n and ("propellant" in n or "booster" in n or "ship" in n)
    ):
        return "prop_complete"
    # GO for prop vs GO for launch
    if (
        "go for propellant" in n
        or "go for prop" in n
        or ("propellant load" in n and ("go" in n or "poll" in n or "verif" in n))
        or ("poll" in n and "prop" in n)
    ):
        return "go_prop"
    if (
        "go for launch" in n
        or ("verif" in n and "go" in n and "launch" in n)
        or ("launch director" in n and "go" in n)
        or ("flight director" in n and "go" in n and "prop" not in n)
    ):
        return "go_launch"
    # Propellant / LOX / RP-1 / methane tanking
    if (
        "propellant load" in n
        or "lox" in n
        or "rp-1" in n
        or "rp1" in n
        or "fuel load" in n
        or "liquid methane" in n
        or "liquid oxygen" in n
        or "kerosene" in n
        or "tanking" in n
    ):
        return "prop_load"
    return None


def stage_kind_from_name(name: str) -> str:
    """Map timeline event title → stage art key (SpaceX F9 + Starship aware)."""
    if not c_assert(name is not None, "name required"):
        return "ascent"
    n = (name or "").lower()
    if not c_assert(isinstance(n, str), "name str"):
        return "ascent"
    # Pre-launch first so "hold window" / prop phrases win over complete/ascent
    pre = _kind_prelaunch(n)
    if pre:
        return pre
    if "liftoff" in n or "excitement guaranteed" in n or n.strip() in ("launch", "t-0", "t0"):
        return "liftoff"
    if "max q" in n or "maxq" in n:
        return "maxq"
    if "hot-stag" in n or "hot stag" in n:
        return "hot_stage"
    if "fairing" in n:
        return "fairing"
    if "boostback" in n:
        return "boostback"
    if "stages separate" in n or "stage separation" in n or "1st and 2nd stages separate" in n:
        return "stage_sep"
    if "meco" in n or "main engine cutoff" in n:
        return "meco"
    if "entry burn" in n:
        return "entry_burn"
    land = _kind_landingish(n)
    if land:
        return land
    if "transonic" in n or "subsonic" in n or ("entry" in n and "burn" not in n):
        return "ship_entry"
    # Deploy before engineish so "Second … deploys" is not misread as SECO
    if "deploy" in n or "payload" in n or "satellite" in n or "pod deploy" in n:
        return "deploy"
    eng = _kind_engineish(n)
    if eng:
        return eng
    if "mission complete" in n or n.strip() in ("complete", "success", "reset"):
        return "complete"
    if "complete" in n and "deploy" not in n and "load" not in n:
        return "complete"
    return "ascent"


def stage_scene(kind: str, tick: int) -> list[str]:
    """Animated ASCII frame for a flight stage kind (~0.5s frame step)."""
    if not c_assert(isinstance(tick, int), "tick int"):
        return list(_STAGE_ASCENT[0])
    if not c_assert(isinstance(kind, str), "kind str"):
        return list(_STAGE_ASCENT[0])
    frames = _STAGE_KIND_ART.get(kind) or _STAGE_ASCENT
    if not frames:
        return list(_STAGE_ASCENT[0])
    return list(frames[blink_phase(tick) % len(frames)][:MAX_ASCII_ROWS])


def stage_scene_for_event(event_name: str, tick: int) -> list[str]:
    if not c_assert(event_name is not None, "event name"):
        return stage_scene("ascent", tick)
    if not c_assert(isinstance(tick, int), "tick int"):
        return stage_scene("ascent", 0)
    return stage_scene(stage_kind_from_name(event_name), tick)


# ── Starfield ───────────────────────────────────────────────────

class Starfield:
    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.stars: list[tuple[float, float, int]] = []  # x, y frac, phase
        self._w = 0
        self._h = 0

    def resize(self, w: int, h: int) -> None:
        if not c_assert(isinstance(w, int) and isinstance(h, int), "w/h int"):
            return
        if not c_assert(w >= 0 and h >= 0, "w/h non-negative"):
            return
        if w == self._w and h == self._h:
            return
        self._w, self._h = w, h
        n = max(8, min(MAX_ASCII_ROWS * MAX_ASCII_COLS // 40, (w * h) // 40))
        n = min(n, MAX_LOOP_DEFAULT)
        self.stars = []
        for _ in range(n):
            self.stars.append(
                (self.rng.random(), self.rng.random(), self.rng.randint(0, 7))
            )

    def cells(self, tick: int) -> list[tuple[int, int, str]]:
        """Return (y, x, char) for twinkling stars."""
        if not c_assert(isinstance(tick, int), "tick int"):
            return []
        if not c_assert(self._w >= 0 and self._h >= 0, "starfield sized"):
            return []
        chars = "·.+*✦·.+*"
        out: list[tuple[int, int, str]] = []
        for xf, yf, phase in take_at_most(self.stars, MAX_LOOP_DEFAULT):
            x = int(xf * max(1, self._w - 1))
            y = int(yf * max(1, self._h - 1))
            ch = chars[(phase + tick // 2) % len(chars)]
            if (phase + tick) % 5 == 0:
                ch = " "
            out.append((y, x, ch))
        return out


# ── Progress / bars ─────────────────────────────────────────────

def progress_bar(frac: float, width: int, fill: str = "█", empty: str = "░") -> str:
    if not c_assert(width is not None, "width required"):
        return ""
    if not c_assert(math.isfinite(float(frac)), "frac finite"):
        frac = 0.0
    width = max(4, min(int(width), MAX_ASCII_COLS))
    frac = max(0.0, min(1.0, float(frac)))
    n = int(round(frac * width))
    return fill * n + empty * (width - n)


def sparkline(values: list[float], width: int) -> str:
    if not c_assert(values is not None, "values required"):
        return ""
    if not c_assert(isinstance(width, int), "width int"):
        return ""
    if not values or width < 1:
        return ""
    width = min(width, MAX_ASCII_COLS)
    vals = take_at_most(values, MAX_LOOP_DEFAULT)
    blocks = " ▁▂▃▄▅▆▇█"
    mn, mx = min(vals), max(vals)
    span = (mx - mn) or 1.0
    out: list[str] = []
    for i in range(width):
        idx = int(i * (len(vals) - 1) / max(1, width - 1))
        v = vals[idx]
        bi = int((v - mn) / span * (len(blocks) - 1))
        out.append(blocks[bi])
    return "".join(out)


def spinner(tick: int) -> str:
    if not c_assert(isinstance(tick, int), "tick int"):
        return "·"
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    if not c_assert(len(frames) == 10, "spinner frames"):
        return "·"
    return frames[tick % 10]


def pulse_prefix(tick: int, live: bool = False) -> str:
    if not c_assert(isinstance(tick, int), "tick int"):
        return "·"
    if not c_assert(isinstance(live, bool), "live bool"):
        live = False
    if live:
        return "●" if blink_on(tick) else "○"
    frames = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
    # Slow non-live bar so it is not a seizure light
    return frames[blink_phase(tick) % len(frames)]


def banner_spaceflight(tick: int = 0) -> str:
    if not c_assert(isinstance(tick, int), "tick int"):
        tick = 0
    if not c_assert(True, "banner entry"):
        return "SPACEFLIGHT"
    frames = [
        "✦ SPACEFLIGHT ✦",
        "✧ SPACEFLIGHT ✧",
        "⋆ SPACEFLIGHT ⋆",
        "✧ SPACEFLIGHT ✧",
    ]
    return frames[tick % len(frames)]


def mission_control_deco(width: int, tick: int) -> str:
    if not c_assert(isinstance(width, int), "width int"):
        return ""
    if not c_assert(isinstance(tick, int), "tick int"):
        tick = 0
    width = max(0, min(width, MAX_ASCII_COLS))
    edge = "═" * max(0, (width - 20) // 2)
    mid = f"⟨ MC-{tick % 1000:03d} ⟩"
    s = edge + mid + edge
    return s[:width]
