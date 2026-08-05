"""
ASCII projected flight path / trajectory visualization.

This is a simplified physics sketch for fun, not a guidance sim:
  - Gravity-turn style ascent to target orbit class
  - Optional booster RTLS/ASDS return arc
  - Animated vehicle marker vs T+/countdown phase
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import Launch
from ..p10 import (
    MAX_ASCII_COLS,
    MAX_ASCII_ROWS,
    MAX_PATH_SEGMENTS,
    MAX_STAGE_EVENTS,
    c_assert,
    take_at_most,
)


@dataclass
class TrajectoryPoint:
    t: float  # seconds from liftoff
    x_km: float  # downrange
    y_km: float  # altitude
    stage: str  # boost / sep / upper / coast / orbit / land


def _orbit_params(L: Launch) -> dict:
    if not c_assert(L is not None, "launch required"):
        return {"apo_km": 400, "range_km": 1800, "circular": True, "label": "LEO"}
    if not c_assert(hasattr(L, "payload"), "launch has payload"):
        return {"apo_km": 400, "range_km": 1800, "circular": True, "label": "LEO"}
    orbit = (L.payload.orbit or "").lower()
    abbrev = (L.payload.orbit_abbrev or "").lower()
    name = (L.vehicle.full_name or L.vehicle.name or L.name or "").lower()

    if "suborbital" in orbit or "sub" in abbrev:
        return {"apo_km": 150, "range_km": 200, "circular": False, "label": "Suborbital"}
    if "gto" in abbrev or "geostationary" in orbit or "transfer" in orbit:
        return {"apo_km": 35000, "range_km": 8000, "circular": False, "label": "GTO"}
    if "geo" in abbrev or "geostationary" in orbit:
        return {"apo_km": 35786, "range_km": 12000, "circular": True, "label": "GEO"}
    if "sso" in abbrev or "sun-sync" in orbit or "polar" in orbit:
        return {"apo_km": 600, "range_km": 2200, "circular": True, "label": "SSO/Polar"}
    if "heo" in abbrev or "molniya" in orbit:
        return {"apo_km": 40000, "range_km": 10000, "circular": False, "label": "HEO"}
    if "meo" in abbrev:
        return {"apo_km": 20000, "range_km": 6000, "circular": True, "label": "MEO"}
    if "starship" in name:
        return {"apo_km": 250, "range_km": 1200, "circular": False, "label": "LEO/Test"}
    return {"apo_km": 400, "range_km": 1800, "circular": True, "label": "LEO"}


def _landing_params(L: Launch, rng: float) -> tuple[bool, float]:
    if not c_assert(L is not None, "launch required"):
        return False, 0.0
    if not c_assert(rng >= 0, "range non-negative"):
        return False, 0.0
    has_landing = False
    land_x = 0.0
    boosters = take_at_most(L.vehicle.boosters or [], MAX_STAGE_EVENTS)
    for b in boosters[:MAX_STAGE_EVENTS]:
        if b.landing_attempt:
            has_landing = True
            loc = (b.landing_location or b.landing_type or "").lower()
            if any(k in loc for k in ("asds", "drone", "ocisly", "jrti", "a shortfall", "just read")):
                land_x = min(rng * 0.35, 700)
            else:
                land_x = 20.0
            break
    return has_landing, land_x


def _ascent_point(t: float, t_sep: float, t_secoa: float, t_orbit: float, apo: float, rng: float, circular: bool) -> TrajectoryPoint:
    if not c_assert(t >= 0, "t non-negative"):
        t = 0.0
    if not c_assert(apo > 0 and rng > 0, "apo/rng positive"):
        apo, rng = 400.0, 1800.0
    if t <= t_sep:
        frac = t / t_sep
        y = apo * 0.25 * (frac**1.4)
        x = rng * 0.15 * (frac**1.6)
        stage = "boost"
    elif t <= t_secoa:
        frac = (t - t_sep) / (t_secoa - t_sep)
        y0 = apo * 0.25
        y = y0 + (apo * 0.85 - y0) * (frac**0.9)
        x0 = rng * 0.15
        x = x0 + (rng * 0.75 - x0) * frac
        stage = "upper"
    else:
        frac = min(1.0, (t - t_secoa) / max(1.0, t_orbit - t_secoa))
        y = apo * 0.85 + (apo - apo * 0.85) * math.sin(frac * math.pi / 2)
        x = rng * 0.75 + (rng - rng * 0.75) * frac
        stage = "orbit" if circular and frac > 0.7 else "coast"
        if frac > 0.95 and circular:
            y = apo
    return TrajectoryPoint(t=t, x_km=x, y_km=y, stage=stage)


def generate_trajectory(L: Launch, n: int = 80) -> list[TrajectoryPoint]:
    """Generate a stylized ascent + optional landing path."""
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(isinstance(n, int) and n > 0, "n positive"):
        n = 80
    n = min(n, MAX_PATH_SEGMENTS)
    p = _orbit_params(L)
    apo = p["apo_km"]
    rng = p["range_km"]
    pts: list[TrajectoryPoint] = []

    t_sep = 150.0 if "falcon" in (L.vehicle.name or "").lower() else 180.0
    t_secoa = 540.0
    t_orbit = 600.0 if apo < 1000 else 1500.0
    t_end = t_orbit + 120.0

    has_landing, land_x = _landing_params(L, rng)

    for i in range(n):
        t = t_end * i / max(1, n - 1)
        pts.append(_ascent_point(t, t_sep, t_secoa, t_orbit, apo, rng, p["circular"]))

    if has_landing:
        for i in range(12):
            frac = i / 11
            y_sep = apo * 0.25
            y = y_sep * (1 - frac) ** 1.2
            x = (rng * 0.15) + (land_x - rng * 0.15) * frac
            pts.append(TrajectoryPoint(t=t_sep + frac * 360, x_km=x, y_km=y, stage="land"))

    return pts


def vehicle_progress(L: Launch, now: datetime | None = None) -> float:
    """0..1 position along nominal trajectory based on wall clock."""
    if not c_assert(L is not None, "launch required"):
        return 0.0
    if not c_assert(True, "vehicle_progress entry"):
        return 0.0
    now = now or datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    if secs is None:
        return 0.0
    if secs > 0:
        return 0.0
    t_plus = -secs
    return max(0.0, min(1.0, t_plus / 600.0))


def _put_grid(
    grid: list[list[str]],
    plot_w: int,
    plot_h: int,
    max_x: float,
    max_y: float,
    x_km: float,
    y_km: float,
    ch: str,
) -> None:
    if not c_assert(plot_w > 0 and plot_h > 0, "plot dims"):
        return
    if not c_assert(max_x > 0 and max_y > 0, "max_x/y"):
        return
    xi = int(x_km / max_x * (plot_w - 1))
    yi = int(y_km / max_y * (plot_h - 1))
    yi = plot_h - 1 - yi
    if 0 <= xi < plot_w and 0 <= yi < plot_h:
        if grid[yi][xi] not in ("▲", "🚀", "◆"):
            grid[yi][xi] = ch


def _draw_paths(
    grid: list[list[str]],
    plot_w: int,
    plot_h: int,
    max_x: float,
    max_y: float,
    apo: float,
    ascent: list[TrajectoryPoint],
    land: list[TrajectoryPoint],
) -> None:
    if not c_assert(grid is not None, "grid required"):
        return
    if not c_assert(plot_w > 0, "plot_w"):
        return
    for xi in range(plot_w):
        _put_grid(grid, plot_w, plot_h, max_x, max_y, max_x * xi / max(1, plot_w - 1), apo, "·")
    stage_ch = {"boost": "█", "upper": "▓", "coast": "▒", "orbit": "░"}
    for p in take_at_most(ascent, MAX_PATH_SEGMENTS):
        ch = stage_ch.get(p.stage, "•")
        _put_grid(grid, plot_w, plot_h, max_x, max_y, p.x_km, p.y_km, ch)
    for p in take_at_most(land, MAX_PATH_SEGMENTS):
        _put_grid(grid, plot_w, plot_h, max_x, max_y, p.x_km, p.y_km, "╌")
    _put_grid(grid, plot_w, plot_h, max_x, max_y, 0, 0, "▲")
    if land:
        _put_grid(grid, plot_w, plot_h, max_x, max_y, land[-1].x_km, 0, "■")


def _draw_vehicle(
    grid: list[list[str]],
    plot_w: int,
    plot_h: int,
    max_x: float,
    max_y: float,
    L: Launch,
    ascent: list[TrajectoryPoint],
    tick: int,
    now: datetime,
) -> None:
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(grid is not None, "grid"):
        return
    prog = vehicle_progress(L, now)
    secs = L.seconds_to_net(now)
    if secs is not None and secs > 0:
        _put_grid(grid, plot_w, plot_h, max_x, max_y, 2 + math.sin(tick / 3) * 0, 2 + abs(math.sin(tick / 5)), "◆")
        return
    if not ascent:
        return
    idx = min(len(ascent) - 1, int(prog * (len(ascent) - 1)))
    p = ascent[idx]
    _put_grid(grid, plot_w, plot_h, max_x, max_y, p.x_km, p.y_km, "▲")
    if 0.02 < prog < 0.95:
        ch = "░" if tick % 2 else "▒"
        _put_grid(grid, plot_w, plot_h, max_x, max_y, p.x_km, max(0, p.y_km - max_y * 0.03), ch)


def _compose_grid_lines(
    grid: list[list[str]],
    width: int,
    plot_w: int,
    plot_h: int,
    max_x: float,
    max_y: float,
    title: str,
) -> list[str]:
    if not c_assert(grid is not None, "grid"):
        return []
    if not c_assert(width > 0, "width"):
        return []
    lines: list[str] = []
    lines.append(title[:width].ljust(width)[:width])
    for row_i in range(min(plot_h, len(grid))):
        row = grid[row_i]
        if row_i == 0:
            label = f"{int(max_y):>5}km"
        elif row_i == plot_h - 1:
            label = "    0km"
        elif row_i == plot_h // 2:
            label = f"{int(max_y / 2):>5}km"
        else:
            label = "       "
        lines.append((label[-7:] + "│" + "".join(row))[:width])
    axis = "       └" + "─" * plot_w
    lines.append(axis[:width])
    xlab = f"       pad{' ' * max(1, plot_w // 2 - 8)}downrange → {int(max_x)}km"
    lines.append(xlab[:width].ljust(width)[:width])
    return lines


def render_flightpath(
    L: Launch,
    width: int,
    height: int,
    tick: int = 0,
    now: datetime | None = None,
) -> list[str]:
    """
    Render ASCII plot as list of strings (no color).
    height includes axis labels row.
    """
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(isinstance(width, int) and isinstance(height, int), "dims int"):
        return []
    now = now or datetime.now(timezone.utc)
    width = max(24, min(width, MAX_ASCII_COLS))
    height = max(10, min(height, MAX_ASCII_ROWS))
    plot_h = height - 3
    plot_w = width - 8

    params = _orbit_params(L)
    pts = generate_trajectory(L, n=max(40, min(plot_w, MAX_PATH_SEGMENTS)))
    ascent = [p for p in take_at_most(pts, MAX_PATH_SEGMENTS) if p.stage != "land"]
    land = [p for p in take_at_most(pts, MAX_PATH_SEGMENTS) if p.stage == "land"]

    max_x = max((p.x_km for p in take_at_most(pts, MAX_PATH_SEGMENTS)), default=1.0) * 1.05
    max_y = max(params["apo_km"] * 1.1, max((p.y_km for p in take_at_most(pts, MAX_PATH_SEGMENTS)), default=1.0) * 1.05)

    grid = [[" " for _ in range(plot_w)] for _ in range(plot_h)]
    apo = params["apo_km"]
    _draw_paths(grid, plot_w, plot_h, max_x, max_y, apo, ascent, land)
    _draw_vehicle(grid, plot_w, plot_h, max_x, max_y, L, ascent, tick, now)

    vname = L.vehicle.full_name or L.vehicle.name or L.vehicle_name()
    title = f"TRAJECTORY  {vname} → {params['label']}  apo~{int(apo)}km"
    lines = _compose_grid_lines(grid, width, plot_w, plot_h, max_x, max_y, title)
    return lines[:height]


def _telemetry_prelaunch(L: Launch, secs: float, params: dict) -> list[str]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(params is not None, "params"):
        return []
    lines = [
        f"PHASE   PRE-LAUNCH  (T-{_fmt(secs)})",
        "MODE    COUNTDOWN / HOLD CHECKS",
        f"TARGET  {params['label']}  ~{int(params['apo_km'])} km",
    ]
    if secs < 3600:
        lines.append("LOX     LOADING ▓▓▓▓▓▓▓░")
        if "starship" in (L.vehicle.name or "").lower():
            lines.append("CH4/RP1 LOADING ▓▓▓▓▓▓░░")
        else:
            lines.append("RP-1    READY   ████████")
    else:
        lines.append("PROP    STANDBY")
    lines.append(f"PAD     {L.pad or '—'} @ {L.location or '—'}")
    if L.vehicle.boosters:
        b = L.vehicle.boosters[0]
        lines.append(f"BOOSTER {b.serial or '—'}  flight #{b.flights or '?'}")
    return lines


def _telemetry_ascent(L: Launch, secs: float, params: dict, now: datetime) -> list[str]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(params is not None, "params"):
        return []
    t_plus = -secs
    prog = vehicle_progress(L, now)
    alt = params["apo_km"] * min(1.0, prog * 1.2)
    vel = min(7800, prog * 7800 * 1.05)
    lines = [
        f"PHASE   ASCENT  T+{_fmt(t_plus)}",
        f"ALT     {alt:8.1f} km",
        f"VEL     {vel:8.0f} m/s",
        f"Q       {max(0, 30 - abs(prog - 0.15) * 80):5.1f} kPa  (approx)",
    ]
    if prog < 0.25:
        lines.append("EVENT   MAX-Q WINDOW" if 0.1 < prog < 0.2 else "EVENT   LIFTOFF / CLEAR TOWER")
    elif prog < 0.4:
        lines.append("EVENT   MECO / STAGE SEP")
    elif prog < 0.85:
        lines.append("EVENT   UPPER COAST / BURN")
    else:
        lines.append("EVENT   ORBITAL INSERTION WINDOW")
    for b in take_at_most(L.vehicle.boosters or [], MAX_STAGE_EVENTS):
        if b.landing_attempt:
            lines.append(f"LANDING {b.landing_type or 'attempt'} → {b.landing_location or '?'}")
    return lines


def telemetry_readout(L: Launch, now: datetime | None = None, tick: int = 0) -> list[str]:
    """Fake-but-plausible telemetry lines for flash factor."""
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(isinstance(tick, int), "tick int"):
        tick = 0
    now = now or datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    params = _orbit_params(L)
    if secs is None:
        return ["NET unknown — trajectory on hold"]
    if secs > 0:
        lines = _telemetry_prelaunch(L, secs, params)
    else:
        lines = _telemetry_ascent(L, secs, params, now)
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[tick % 10]
    lines.append(f"{spin} guidance sketch · not a real-time radar track")
    return lines


def _fmt(s: float) -> str:
    if not c_assert(s is not None, "s required"):
        return "00:00"
    if not c_assert(True, "_fmt entry"):
        return "00:00"
    s = int(abs(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
