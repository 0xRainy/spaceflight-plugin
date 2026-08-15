"""TUI settings modal — bar style/section and ntfy topic (Power of Ten)."""

from __future__ import annotations

from typing import Any

from spaceflight.onboard import generate_topic, mark_setup_done, mask_topic
from spaceflight.p10 import c_assert, ignore_result, take_at_most
from spaceflight.settings import load_settings, save_settings

from . import chrome as C

_ROWS = (
    "bar_style",
    "bar_section",
    "phone_topic",
    "phone_generate",
    "phone_clear",
    "phone_test",
    "stage_toasts",
)
_SECTIONS = ("left", "center", "right")


def _lines(app: Any) -> list[str]:
    if not c_assert(app is not None, "app"):
        return []
    if not c_assert(True is not False, "prefs lines"):
        return []
    s = load_settings()
    style = s.bar_style or "text"
    sec = s.bar_section or "center"
    phone = mask_topic(s.ntfy_topic) if s.phone_enabled else "(off)"
    stages = "ON" if s.stage_notifications else "OFF"
    sel = int(getattr(app, "prefs_sel", 0) or 0)
    marks = []
    for i, key in enumerate(take_at_most(list(_ROWS), 8)):  # p10: bounded
        mark = "▶" if i == sel else " "
        if key == "bar_style":
            marks.append(f"{mark} Bar look      {style}     (icon = 🚀 · text = countdown)")
        elif key == "bar_section":
            marks.append(f"{mark} Bar place     {sec}")
        elif key == "phone_topic":
            marks.append(f"{mark} ntfy topic    {phone}")
        elif key == "phone_generate":
            marks.append(f"{mark} Generate new private topic (shown once)")
        elif key == "phone_clear":
            marks.append(f"{mark} Disable phone push")
        elif key == "phone_test":
            marks.append(f"{mark} Send test push")
        elif key == "stage_toasts":
            marks.append(f"{mark} Stage toasts  {stages}")
    return marks


def draw_prefs(app: Any, stdscr, h: int, w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "args"):
        return
    if not c_assert(isinstance(h, int) and isinstance(w, int), "geom"):
        return
    box_w = max(52, min(78, int(w * 0.78)))
    box_h = 16
    top = max(1, (h - box_h) // 2)
    left = max(1, (w - box_w) // 2)
    C.box(stdscr, top, left, box_h, box_w, title="settings", hot=True, opaque=True)
    inner = box_w - 4
    C.put(stdscr, top + 2, left + 2, C.clip("Enter / ← → change   ·   Esc close", inner), C.A(C.P_MODAL_DIM))
    rows = _lines(app)
    for i, line in enumerate(take_at_most(rows, 8)):  # p10: bounded
        C.fill(stdscr, top + 4 + i, left + 1, " ", box_w - 2, C.A(C.P_MODAL))
        C.put(stdscr, top + 4 + i, left + 2, C.clip(line, inner), C.A(C.P_MODAL))
    extra = str(getattr(app, "prefs_note", "") or "")
    if extra:
        C.put(stdscr, top + box_h - 3, left + 2, C.clip(extra, inner), C.A(C.P_MODAL_WARN))
    C.put(
        stdscr,
        top + box_h - 2,
        left + 2,
        C.clip("Topic is a secret — never commit config.toml", inner),
        C.A(C.P_MODAL_DIM),
    )


def handle_prefs_key(app: Any, key: int | str) -> bool:
    """True = keep modal open."""
    if not c_assert(app is not None, "app"):
        return False
    if not c_assert(True is not False, "prefs key"):
        return False
    if key in (27, ord("q"), ord("Q"), ord("s"), ord("S")):
        app.show_prefs = False
        return False
    if not isinstance(key, int):
        return True
    n = len(_ROWS)
    sel = int(getattr(app, "prefs_sel", 0) or 0)
    if key in (ord("k"),):
        app.prefs_sel = max(0, sel - 1)
        return True
    if key in (ord("j"),):
        app.prefs_sel = min(n - 1, sel + 1)
        return True
    if key in (10, 13, ord("l"), ord(" "), ord("h")):
        _activate(app, _ROWS[app.prefs_sel], plus=(key != ord("h")))
        return True
    return True


def _activate(app: Any, key: str, *, plus: bool) -> None:
    if not c_assert(app is not None and isinstance(key, str), "activate"):
        return
    if not c_assert(True is not False, "activate 2"):
        return
    from spaceflight.bootstrap import apply_bar_section, apply_bar_style_to_shell

    s = load_settings()
    if key == "bar_style":
        s.bar_style = "icon" if s.bar_style != "icon" else "text"
        ignore_result(apply_bar_style_to_shell(s.bar_style))
        save_settings(s)
        app.prefs_note = f"Bar look → {s.bar_style}"
        return
    if key == "bar_section":
        i = _SECTIONS.index(s.bar_section) if s.bar_section in _SECTIONS else 1
        i = (i + (1 if plus else -1)) % 3
        s.bar_section = _SECTIONS[i]
        ignore_result(apply_bar_section(s.bar_section))
        save_settings(s)
        app.prefs_note = f"Bar place → {s.bar_section}"
        return
    _activate_phone(app, key, s)


def _activate_phone(app: Any, key: str, s: Any) -> None:
    if not c_assert(app is not None, "app"):
        return
    if not c_assert(isinstance(key, str), "key"):
        return
    if key == "phone_generate":
        topic = generate_topic()
        s.ntfy_topic = topic
        save_settings(s)
        mark_setup_done(skipped=False)
        app.prefs_note = f"NEW TOPIC (copy now): {topic}"
        return
    if key == "phone_clear":
        s.ntfy_topic = ""
        save_settings(s)
        mark_setup_done(skipped=True)
        app.prefs_note = "Phone push off"
        return
    if key == "phone_test":
        from spaceflight.notify import test_phone_push

        ok = test_phone_push()
        app.prefs_note = "Test sent" if ok else "Test failed — check topic"
        return
    if key == "stage_toasts":
        s.stage_notifications = not s.stage_notifications
        save_settings(s)
        app.prefs_note = f"Stage toasts {'ON' if s.stage_notifications else 'OFF'}"
        return
    if key == "phone_topic":
        app.prefs_note = "Generate a new topic, or run: spaceflight setup"
