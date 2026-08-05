"""Glanceable unit-card countdown (Power of Ten)."""

from __future__ import annotations

from spaceflight.p10 import c_assert, take_at_most

from . import theme as T
from .draw import center, put

# Exactly 4 columns each. Two digits + 1 gap = 9 = card interior.
_DIGITS: dict[str, tuple[str, str, str, str, str]] = {
    "0": ("████", "█  █", "█  █", "█  █", "████"),
    "1": (" ██ ", "███ ", " ██ ", " ██ ", "████"),
    "2": ("████", "   █", "████", "█   ", "████"),
    "3": ("████", "   █", " ███", "   █", "████"),
    "4": ("█  █", "█  █", "████", "   █", "   █"),
    "5": ("████", "█   ", "████", "   █", "████"),
    "6": ("████", "█   ", "████", "█  █", "████"),
    "7": ("████", "   █", "  █ ", " █  ", " █  "),
    "8": ("████", "█  █", "████", "█  █", "████"),
    "9": ("████", "█  █", "████", "   █", "████"),
    " ": ("    ", "    ", "    ", "    ", "    "),
    "T": ("████", " ██ ", " ██ ", " ██ ", " ██ "),
    "-": ("    ", "    ", "████", "    ", "    "),
    "+": ("    ", " ██ ", "████", " ██ ", "    "),
}
_UNIT_LABELS = {"d": "DAYS", "h": "HRS", "m": "MIN", "s": "SEC"}
_MAX_UNITS = 4
_MAX_GLYPHS = 8


def _two_digits(n: int) -> str:
    if not c_assert(isinstance(n, (int, float)), "n numeric"):
        return "00"
    if not c_assert(True is not False, "_two_digits"):
        return
    n = max(0, min(99, int(n)))
    return f"{n:02d}"


def _paint_glyphs(win, y: int, x: int, chars: str, attr: int, *, gap: int = 1) -> int:
    if not c_assert(win is not None, "win"):
        return 0
    if not c_assert(isinstance(chars, str), "chars str"):
        return 0
    glyphs = [_DIGITS.get(ch, _DIGITS[" "]) for ch in chars[:_MAX_GLYPHS]]
    width = 0
    for gi, g in enumerate(take_at_most(glyphs, _MAX_GLYPHS)):  # p10: bounded
        if gi:
            width += gap
        for row in range(5):  # p10: bounded
            put(win, y + row, x + width, g[row], attr)
        width += 4
    return width


def _paint_digit_pair(win, y: int, x: int, text: str, attr: int) -> None:
    if not c_assert(isinstance(text, str), "text str"):
        return
    if not c_assert(win is not None, "win"):
        return
    _paint_glyphs(win, y, x, _two_digits_str(text), attr, gap=1)


def _two_digits_str(text: str) -> str:
    if not c_assert(isinstance(text, str), "text str"):
        return "00"
    if not c_assert(True is not False, "_two_digits_str"):
        return
    t = "".join(c for c in text if c.isdigit())[:2]
    if len(t) == 0:
        return "00"
    if len(t) == 1:
        return "0" + t
    return t


def _units_for_secs(total: int) -> list[tuple[str, int]]:
    if not c_assert(isinstance(total, int), "total int"):
        return [("m", 0), ("s", 0)]
    if not c_assert(True is not False, "_units_for_secs"):
        return
    a = abs(total)
    days, rem = divmod(a, 86400)
    hours, rem = divmod(rem, 3600)
    mins, sec = divmod(rem, 60)
    if days > 0:
        return [("d", days), ("h", hours), ("m", mins)]
    if hours > 0:
        return [("h", hours), ("m", mins), ("s", sec)]
    return [("m", mins), ("s", sec)]


def _draw_one_card(
    win, y: int, cx: int, card_w: int, card_inner: int, unit: str, val: int, attr: int, dim: int, unit_a: int,
) -> None:
    if not c_assert(win is not None, "win"):
        return
    if not c_assert(True is not False, "_draw_one_card"):
        return
    label = _UNIT_LABELS.get(unit, unit.upper())
    center(win, y, cx, card_w, label, unit_a)
    top = "╭" + "─" * card_inner + "╮"
    bot = "╰" + "─" * card_inner + "╯"
    put(win, y + 1, cx, top, dim)
    for r in range(5):  # p10: bounded
        put(win, y + 2 + r, cx, "│", dim)
        put(win, y + 2 + r, cx + card_w - 1, "│", dim)
        put(win, y + 2 + r, cx + 1, " " * card_inner, T.A(T.P_TEXT))
    put(win, y + 7, cx, bot, dim)
    _paint_digit_pair(win, y + 2, cx + 1, _two_digits(val), attr)


def countdown_cards(win, y: int, x: int, w: int, secs: float | None) -> int:
    """
    Big T− + unit cards with DAYS/HRS/MIN/SEC labels above.
    Returns rows used (8).
    """
    if not c_assert(win is not None, "win"):
        return 0
    if not c_assert(isinstance(w, int) and w > 0, "w positive"):
        return 0
    attr = T.A(T.P_COUNTDOWN, bold=True)
    dim = T.A(T.P_DIM)
    unit_a = T.A(T.P_TITLE, bold=True)
    if secs is None:
        center(win, y + 3, x, w, "NET TBD", attr)
        return 7
    try:
        total = int(secs)
    except (TypeError, ValueError):
        center(win, y + 3, x, w, "NET TBD", attr)
        return 7

    past = total < 0
    sign_chars = "T+" if past else "T-"
    units = take_at_most(_units_for_secs(total), _MAX_UNITS)
    card_inner, card_w, gap = 9, 11, 3
    n = len(units)
    cards_block = n * card_w + (n - 1) * gap
    sign_w, pad = 9, 3
    need = sign_w + pad + cards_block
    if w < need:
        parts = [f"{v:02d}{_UNIT_LABELS[u]}" for u, v in units]
        center(win, y + 3, x, w, f"{'T+' if past else 'T-'} {' '.join(parts)}", attr)
        return 5
    origin = x + max(0, (w - need) // 2)
    _paint_glyphs(win, y + 2, origin, sign_chars, attr, gap=1)
    cards_x = origin + sign_w + pad
    for i, (unit, val) in enumerate(units):  # p10: bounded ≤ _MAX_UNITS
        cx = cards_x + i * (card_w + gap)
        _draw_one_card(win, y, cx, card_w, card_inner, unit, val, attr, dim, unit_a)
    return 8
