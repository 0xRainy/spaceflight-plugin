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


@dataclass
class TrajectoryPoint:
    t: float  # seconds from liftoff
    x_km: float  # downrange
    y_km: float  # altitude
    stage: str  # boost / sep / upper / coast / orbit / land


def _orbit_params(L: Launch) -> dict:
    orbit = (L.payload.orbit or "").lower()
    abbrev = (L.payload.orbit_abbrev or "").lower()
    name = (L.vehicle.full_name or L.vehicle.name or L.name or "").lower()

    # target altitude (km) and downrange scale
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
    # LEO default
    if "starship" in name:
        return {"apo_km": 250, "range_km": 1200, "circular": False, "label": "LEO/Test"}
    return {"apo_km": 400, "range_km": 1800, "circular": True, "label": "LEO"}


def generate_trajectory(L: Launch, n: int = 80) -> list[TrajectoryPoint]:
    """Generate a stylized ascent + optional landing path."""
    p = _orbit_params(L)
    apo = p["apo_km"]
    rng = p["range_km"]
    pts: list[TrajectoryPoint] = []

    # Phase times (seconds) — toy model
    t_sep = 150.0 if "falcon" in (L.vehicle.name or "").lower() else 180.0
    t_secoa = 540.0
    t_orbit = 600.0 if apo < 1000 else 1500.0
    t_end = t_orbit + 120.0

    has_landing = False
    land_x = 0.0
    for b in L.vehicle.boosters:
        if b.landing_attempt:
            has_landing = True
            # ASDS is downrange, RTLS near 0
            loc = (b.landing_location or b.landing_type or "").lower()
            if any(k in loc for k in ("asds", "drone", "ocisly", "jrti", "a shortfall", "just read")):
                land_x = min(rng * 0.35, 700)
            else:
                land_x = 20.0  # RTLS-ish
            break

    for i in range(n):
        t = t_end * i / max(1, n - 1)
        if t <= t_sep:
            # boostback: gravity turn
            frac = t / t_sep
            # altitude rises smoothly
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
            stage = "orbit" if p["circular"] and frac > 0.7 else "coast"
            if frac > 0.95 and p["circular"]:
                # flat orbital insert
                y = apo
        pts.append(TrajectoryPoint(t=t, x_km=x, y_km=y, stage=stage))

    # Booster landing branch (separate path for display overlay)
    if has_landing:
        # inject landing markers as extra stage points (returned separately via stage=land)
        for i in range(12):
            frac = i / 11
            # from sep altitude down to sea level / pad
            y_sep = apo * 0.25
            y = y_sep * (1 - frac) ** 1.2
            x = (rng * 0.15) + (land_x - rng * 0.15) * frac
            pts.append(TrajectoryPoint(t=t_sep + frac * 360, x_km=x, y_km=y, stage="land"))

    return pts


def vehicle_progress(L: Launch, now: datetime | None = None) -> float:
    """0..1 position along nominal trajectory based on wall clock."""
    now = now or datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    if secs is None:
        return 0.0
    if secs > 0:
        return 0.0  # on pad
    # post-liftoff: map first ~10 minutes of flight
    t_plus = -secs
    return max(0.0, min(1.0, t_plus / 600.0))


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
    now = now or datetime.now(timezone.utc)
    width = max(24, width)
    height = max(10, height)
    plot_h = height - 3  # title + x-axis label
    plot_w = width - 8  # y-axis labels

    params = _orbit_params(L)
    pts = generate_trajectory(L, n=max(40, plot_w))
    ascent = [p for p in pts if p.stage != "land"]
    land = [p for p in pts if p.stage == "land"]

    max_x = max((p.x_km for p in pts), default=1.0) * 1.05
    max_y = max(params["apo_km"] * 1.1, max((p.y_km for p in pts), default=1.0) * 1.05)

    # grid
    grid = [[" " for _ in range(plot_w)] for _ in range(plot_h)]

    def put(x_km: float, y_km: float, ch: str) -> None:
        xi = int(x_km / max_x * (plot_w - 1))
        yi = int(y_km / max_y * (plot_h - 1))
        yi = plot_h - 1 - yi  # flip Y
        if 0 <= xi < plot_w and 0 <= yi < plot_h:
            # don't overwrite rocket marker with path
            if grid[yi][xi] not in ("▲", "🚀", "◆"):
                grid[yi][xi] = ch

    # orbital target altitude dashed line
    apo = params["apo_km"]
    for xi in range(plot_w):
        put(max_x * xi / max(1, plot_w - 1), apo, "·")

    # path
    for p in ascent:
        ch = {
            "boost": "█",
            "upper": "▓",
            "coast": "▒",
            "orbit": "░",
        }.get(p.stage, "•")
        put(p.x_km, p.y_km, ch)

    for p in land:
        put(p.x_km, p.y_km, "╌")

    # pad
    put(0, 0, "▲")

    # landing site mark
    if land:
        put(land[-1].x_km, 0, "■")

    # vehicle marker
    prog = vehicle_progress(L, now)
    secs = L.seconds_to_net(now)
    if secs is not None and secs > 0:
        # on pad, slight "breathing"
        put(2 + math.sin(tick / 3) * 0, 2 + abs(math.sin(tick / 5)), "◆")
    else:
        # along ascent path
        if ascent:
            idx = min(len(ascent) - 1, int(prog * (len(ascent) - 1)))
            p = ascent[idx]
            # flame flicker offset
            put(p.x_km, p.y_km, "▲")
            if prog > 0.02 and prog < 0.95:
                put(p.x_km, max(0, p.y_km - max_y * 0.03), "░" if tick % 2 else "▒")

    # compose with axes
    lines: list[str] = []
    vname = L.vehicle.full_name or L.vehicle.name or L.vehicle_name()
    title = f"TRAJECTORY  {vname} → {params['label']}  apo~{int(apo)}km"
    lines.append(title[:width].ljust(width)[:width])

    for row_i, row in enumerate(grid):
        # y label every few rows
        y_val = max_y * (plot_h - 1 - row_i) / max(1, plot_h - 1)
        if row_i == 0:
            label = f"{int(max_y):>5}km"
        elif row_i == plot_h - 1:
            label = "    0km"
        elif row_i == plot_h // 2:
            label = f"{int(max_y/2):>5}km"
        else:
            label = "       "
        lines.append((label[-7:] + "│" + "".join(row))[:width])

    # x axis
    axis = "       └" + "─" * (plot_w)
    lines.append(axis[:width])
    xlab = f"       pad{' ' * max(1, plot_w // 2 - 8)}downrange → {int(max_x)}km"
    lines.append(xlab[:width].ljust(width)[:width])

    return lines[:height]


def telemetry_readout(L: Launch, now: datetime | None = None, tick: int = 0) -> list[str]:
    """Fake-but-plausible telemetry lines for flash factor."""
    now = now or datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    params = _orbit_params(L)
    lines = []
    if secs is None:
        lines.append("NET unknown — trajectory on hold")
        return lines

    if secs > 0:
        lines.append(f"PHASE   PRE-LAUNCH  (T-{_fmt(secs)})")
        lines.append("MODE    COUNTDOWN / HOLD CHECKS")
        lines.append(f"TARGET  {params['label']}  ~{int(params['apo_km'])} km")
        # fueling / go-nogo fake status based on time
        if secs < 3600:
            lines.append("LOX     LOADING ▓▓▓▓▓▓▓░")
            lines.append("CH4/RP1 LOADING ▓▓▓▓▓▓░░" if "starship" in (L.vehicle.name or "").lower() else "RP-1    READY   ████████")
        else:
            lines.append("PROP    STANDBY")
        lines.append(f"PAD     {L.pad or '—'} @ {L.location or '—'}")
        if L.vehicle.boosters:
            b = L.vehicle.boosters[0]
            lines.append(f"BOOSTER {b.serial or '—'}  flight #{b.flights or '?'}")
    else:
        t_plus = -secs
        prog = vehicle_progress(L, now)
        alt = params["apo_km"] * min(1.0, prog * 1.2)
        # toy velocity
        vel = min(7800, prog * 7800 * 1.05)
        lines.append(f"PHASE   ASCENT  T+{_fmt(t_plus)}")
        lines.append(f"ALT     {alt:8.1f} km")
        lines.append(f"VEL     {vel:8.0f} m/s")
        lines.append(f"Q       {max(0, 30 - abs(prog - 0.15) * 80):5.1f} kPa  (approx)")
        if prog < 0.25:
            lines.append("EVENT   MAX-Q WINDOW" if 0.1 < prog < 0.2 else "EVENT   LIFTOFF / CLEAR TOWER")
        elif prog < 0.4:
            lines.append("EVENT   MECO / STAGE SEP")
        elif prog < 0.85:
            lines.append("EVENT   UPPER COAST / BURN")
        else:
            lines.append("EVENT   ORBITAL INSERTION WINDOW")
        for b in L.vehicle.boosters:
            if b.landing_attempt:
                lines.append(f"LANDING {b.landing_type or 'attempt'} → {b.landing_location or '?'}")
    # twinkle status
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[tick % 10]
    lines.append(f"{spin} guidance sketch · not a real-time radar track")
    return lines


def _fmt(s: float) -> str:
    s = int(abs(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
