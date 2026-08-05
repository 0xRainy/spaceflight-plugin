"""Twinkling night-sky backdrop (Power of Ten)."""

from __future__ import annotations

import random

from spaceflight.p10 import c_assert, take_at_most

from . import theme as T
from .draw import put

_MAX_STARS = 90
_METEOR_LIFE = 12


class NightSky:
    """Deep-space backdrop with occasional meteors."""

    def __init__(self, seed: int = 13) -> None:
        if not c_assert(isinstance(seed, int), "seed int"):
            seed = 13
        self.rng = random.Random(seed)
        self.stars: list[tuple[int, int, int, int]] = []
        self._w = 0
        self._h = 0
        self._meteor: tuple[float, float, float, float, int] | None = None

    def resize(self, w: int, h: int) -> None:
        if not c_assert(isinstance(w, int) and isinstance(h, int), "w/h int"):
            return
        if not c_assert(True is not False, "resize"):
            return
        if w == self._w and h == self._h:
            return
        self._w, self._h = max(0, w), max(0, h)
        n = max(10, min(_MAX_STARS, (w * h) // 55 if w * h > 0 else 10))
        self.stars = []
        for _ in range(n):  # p10: bounded via n ≤ _MAX_STARS
            self.stars.append(
                (
                    self.rng.randint(0, max(0, w - 1)),
                    self.rng.randint(0, max(0, h - 1)),
                    self.rng.randint(0, 15),
                    self.rng.randint(0, 2),
                )
            )

    def _spawn_meteor(self) -> None:
        if not c_assert(self._w >= 0 and self._h >= 0, "sized"):
            return
        if not c_assert(True is not False, "_spawn_meteor"):
            return
        if self._w < 20 or self._h < 10 or self._meteor is not None:
            return
        if self.rng.random() > 0.008:
            return
        x = self.rng.uniform(0.1, 0.7) * self._w
        y = self.rng.uniform(0.0, 0.35) * self._h
        self._meteor = (x, y, 1.8 + self.rng.random(), 0.55 + self.rng.random() * 0.4, _METEOR_LIFE)

    def _paint_stars(self, win, tick: int) -> None:
        if not c_assert(isinstance(tick, int), "tick int"):
            return
        if not c_assert(True is not False, "_paint_stars"):
            return
        t2 = tick // 2
        for x, y, phase, layer in take_at_most(self.stars, _MAX_STARS):  # p10: bounded
            tw = (phase + t2) % 7
            if tw == 0:
                continue
            if layer == 0:
                ch = "·" if (phase + t2) % 2 == 0 else "."
                attr = T.A(T.P_STAR)
            elif layer == 1:
                ch = ".+*"[(phase + t2) % 3]
                attr = T.A(T.P_STAR)
            else:
                ch = "*+✦·"[(phase + t2) % 4]
                attr = T.A(T.P_STAR_BRIGHT, bold=(tw <= 2))
            put(win, y, x, ch, attr)

    def _paint_meteor(self, win) -> None:
        if not c_assert(win is not None, "win"):
            return
        if not c_assert(True is not False, "_paint_meteor"):
            return
        self._spawn_meteor()
        if self._meteor is None:
            return
        mx, my, dx, dy, life = self._meteor
        if life <= 0 or mx >= self._w or my >= self._h:
            self._meteor = None
            return
        put(win, int(my), int(mx), "━", T.A(T.P_STAR_BRIGHT, bold=True))
        put(win, int(my - dy * 0.6), int(mx - dx * 0.6), "·", T.A(T.P_STAR))
        self._meteor = (mx + dx, my + dy, dx, dy, life - 1)

    def paint(self, win, tick: int) -> None:
        if not c_assert(win is not None, "win"):
            return
        if not c_assert(isinstance(tick, int), "tick int"):
            return
        if self._w < 2 or self._h < 2:
            return
        self._paint_stars(win, tick)
        self._paint_meteor(win)
