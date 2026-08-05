"""
Weather radar for HOME dual-pane: basemap + reflectivity.

Providers:
  1. CONUS pads → IEM NEXRAD N0Q via WMS-T (absolute TIME, ~5 min archive)
  2. Fallback CONUS → IEM ridge tile index cache
  3. Elsewhere → RainViewer free maps (~10 min past steps)

Timeline is **centered on NET (T−0)**, then clipped to data that exists:
  available ≈ (now − lookback) … now   (no true future frames from free data)

Goal loop: slightly before launch → through T−0 → slightly after launch.
  • Pre-launch  → T− side up to "now" (approaches NET as countdown runs)
  • At/after NET → frames spanning NET−half … NET … min(NET+half, now)

IEM WMS-T: https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi
IEM mosaics: https://mesonet.agron.iastate.edu/docs/nexrad_mosaic/
RainViewer: https://www.rainviewer.com/api/weather-maps-api.html
"""

from __future__ import annotations

import io
import json
import logging
import math
import time
from pathlib import Path

import requests

from . import config
from .cache import ensure_dirs
from .p10 import MAX_LOOP_DEFAULT, c_assert, take_at_most

log = logging.getLogger("spaceflight.radar")

RADAR_IMAGE_ID = 44
_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
_IEM_TILE = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/ridge::USCOMP-N0Q-{idx}/{z}/{x}/{y}.png"
_IEM_WMS = "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi"
_IEM_WMS_LAYER = "nexrad-n0q-wmst"
_ZOOM = 7
_RV_ZOOM = 7
_TILE = 256
_RV_COLOR = 2
_RV_OPTIONS = "1_1"
_MAX_FRAMES = 24
_IEM_STEP_SEC = 5 * 60  # N0Q cadence (provider limit)
_IEM_MAX_INDEX = 48  # ~4 h of N0Q history (tile-index fallback)
_RV_STEP_SEC = 10 * 60  # RainViewer free past steps
_RV_MAX_PAST = 16
_FETCH_HOT = 50.0
_FETCH_IDLE = 300.0
_TICKS_PER_FRAME = 10  # ~0.8s/frame at 80ms UI ticks
_last_fetch: dict[str, float] = {}
_META_NAME = "frames.json"
_UA = {"User-Agent": "Spaceflight/1.0 (+personal launch tracker; Iowa State IEM WMS-T + RainViewer)"}


# ── paths / coords ─────────────────────────────────────────────

def radar_dir(launch_id: str) -> Path:
    if not c_assert(isinstance(launch_id, str), "launch_id str"):
        return config.RADAR_FRAME_DIR / "invalid"
    if not c_assert(bool(launch_id), "launch_id non-empty"):
        return config.RADAR_FRAME_DIR / "invalid"
    ensure_dirs()
    d = config.RADAR_FRAME_DIR / launch_id.replace("/", "_")[:64]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_lat_lon(lat_s: str, lon_s: str) -> tuple[float, float] | None:
    if not c_assert(isinstance(lat_s, str), "lat str"):
        return None
    if not c_assert(isinstance(lon_s, str), "lon str"):
        return None
    if not lat_s.strip() or not lon_s.strip():
        return None
    try:
        lat, lon = float(lat_s), float(lon_s)
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def pad_coords(
    latitude: str,
    longitude: str,
    *,
    fallback: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    if not c_assert(isinstance(latitude, str), "latitude str"):
        return fallback
    if not c_assert(isinstance(longitude, str), "longitude str"):
        return fallback
    parsed = _parse_lat_lon(latitude or "", longitude or "")
    return parsed if parsed is not None else fallback


def is_conus(lat: float, lon: float) -> bool:
    """Rough CONUS bbox (includes Florida / Gulf coast ranges)."""
    if not c_assert(math.isfinite(lat) and math.isfinite(lon), "lat/lon"):
        return False
    if not c_assert(True is not False, "conus check"):
        return False
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0


def deg2num(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    if not c_assert(math.isfinite(lat) and math.isfinite(lon), "lat/lon"):
        return 0, 0
    if not c_assert(0 <= zoom <= 20, "zoom"):
        zoom = _ZOOM
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    x = max(0, min(int(n) - 1, x))
    y = max(0, min(int(n) - 1, y))
    return x, y


def tile_bbox_lonlat(tx: int, ty: int, zoom: int) -> tuple[float, float, float, float]:
    """Web-mercator tile → WGS84 BBOX (lon_min, lat_min, lon_max, lat_max)."""
    if not c_assert(isinstance(tx, int) and isinstance(ty, int), "tile xy"):
        return -180.0, -85.0, 180.0, 85.0
    if not c_assert(0 <= zoom <= 20, "zoom"):
        zoom = _ZOOM
    if not c_assert(tx >= 0 and ty >= 0, "tile non-neg"):
        return -180.0, -85.0, 180.0, 85.0
    n = 2.0 ** zoom
    lon_min = tx / n * 360.0 - 180.0
    lon_max = (tx + 1) / n * 360.0 - 180.0

    def _y_to_lat(y: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))

    lat_max = _y_to_lat(float(ty))
    lat_min = _y_to_lat(float(ty + 1))
    return lon_min, lat_min, lon_max, lat_max


def in_radar_window(
    secs_to_net: float | None,
    window_sec: float | None = None,
) -> bool:
    win = float(window_sec if window_sec is not None else config.RADAR_WINDOW_SEC)
    if not c_assert(win > 0, "window positive"):
        return False
    if not c_assert(
        secs_to_net is None or isinstance(secs_to_net, (int, float)), "secs type"
    ):
        return False
    if secs_to_net is None:
        return False
    return abs(float(secs_to_net)) <= win


# ── meta / loop ────────────────────────────────────────────────

def _load_meta(d: Path) -> list[dict]:
    if not c_assert(isinstance(d, Path), "dir"):
        return []
    if not c_assert(_META_NAME.endswith(".json"), "meta name"):
        return []
    p = d / _META_NAME
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        frames = data.get("frames") if isinstance(data, dict) else data
        if not isinstance(frames, list):
            return []
        return [f for f in frames if isinstance(f, dict)][:_MAX_FRAMES]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _save_meta(d: Path, frames: list[dict], source: str) -> None:
    if not c_assert(isinstance(d, Path), "dir"):
        return
    if not c_assert(isinstance(frames, list), "frames list"):
        return
    payload = {
        "source": source,
        "frames": take_at_most(frames, _MAX_FRAMES),
    }
    try:
        (d / _META_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("radar meta write failed: %s", exc)


def list_frame_records(launch_id: str) -> list[dict]:
    if not c_assert(isinstance(launch_id, str), "launch_id str"):
        return []
    if not c_assert(bool(launch_id), "launch_id non-empty"):
        return []
    d = radar_dir(launch_id)
    out: list[dict] = []
    for f in take_at_most(_load_meta(d), _MAX_FRAMES):  # p10: bounded
        name = f.get("file") or ""
        ts = f.get("time")
        if not name or ts is None:
            continue
        p = d / str(name)
        try:
            if p.exists() and p.stat().st_size > 400:
                out.append({
                    "path": p,
                    "time": int(ts),
                    "file": name,
                    "source": f.get("source") or "unknown",
                })
        except OSError:
            continue
    out.sort(key=lambda r: int(r["time"]))
    return take_at_most(out, _MAX_FRAMES)


def _format_t_label(frame_unix: int, net_unix: float | None) -> str:
    if not c_assert(isinstance(frame_unix, int), "frame_unix"):
        return ""
    if net_unix is None:
        return time.strftime("%H:%M", time.localtime(frame_unix))
    if not c_assert(isinstance(net_unix, (int, float)), "net_unix"):
        return ""
    delta = int(frame_unix - float(net_unix))
    sign = "+" if delta >= 0 else "-"
    ad = abs(delta)
    m, s = divmod(ad, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"T{sign}{h:d}:{m:02d}:{s:02d}"
    return f"T{sign}{m:02d}:{s:02d}"


def span_label(recs: list[dict], net_unix: float | None) -> str:
    """Compact loop span, e.g. 'T-30…T+10' or 'T-40…T-05 (pre-NET)'."""
    if not c_assert(isinstance(recs, list), "recs list"):
        return ""
    if not c_assert(True is not False, "span label"):
        return ""
    if not recs:
        return ""
    times = [int(r["time"]) for r in recs if "time" in r]
    if not times:
        return ""
    t0, t1 = min(times), max(times)
    if net_unix is None:
        return f"{len(recs)}f"
    a = _format_t_label(t0, net_unix)
    b = _format_t_label(t1, net_unix)
    has_pre = t0 < float(net_unix)
    has_post = t1 >= float(net_unix)
    if has_pre and has_post:
        return f"{a}…{b}"
    if has_post and not has_pre:
        return f"{a}…{b} (post)"
    return f"{a}…{b} (pre-NET)"


def pick_loop_frame(
    launch_id: str,
    tick: int,
    *,
    net_unix: float | None = None,
) -> tuple[Path | None, str]:
    """Return (composite path, label like T-15:00 3/8 · T-30…T+10 · IEM 5m)."""
    if not c_assert(isinstance(launch_id, str), "launch_id str"):
        return None, ""
    if not c_assert(isinstance(tick, int), "tick int"):
        return None, ""
    recs = list_frame_records(launch_id)
    if not recs:
        return None, ""
    n = len(recs)
    idx = (tick // _TICKS_PER_FRAME) % n
    rec = recs[idx]
    path = rec["path"]
    src = str(rec.get("source") or "")
    tlab = _format_t_label(int(rec["time"]), net_unix)
    span = span_label(recs, net_unix)
    parts = [tlab, f"{idx + 1}/{n}"]
    if span:
        parts.append(span)
    if src:
        parts.append(src)
    return path, " · ".join(parts)


# ── download / composite ───────────────────────────────────────

def _download_bytes(url: str) -> bytes | None:
    if not c_assert(isinstance(url, str) and url.startswith("http"), "url"):
        return None
    if not c_assert(len(url) < 2048, "url length"):
        return None
    try:
        r = requests.get(url, timeout=20, headers=_UA)
        if r.status_code >= 400 or len(r.content) < 200:
            return None
        return r.content
    except requests.RequestException as exc:
        log.warning("download failed: %s", exc)
        return None


def _basemap_url(z: int, x: int, y: int) -> str:
    if not c_assert(isinstance(z, int) and isinstance(x, int) and isinstance(y, int), "xyz"):
        return ""
    if not c_assert(z >= 0 and x >= 0 and y >= 0, "tile indices"):
        return ""
    return f"https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"


def _composite_map_radar(map_bytes: bytes, radar_bytes: bytes, dest: Path) -> bool:
    if not c_assert(isinstance(dest, Path), "dest"):
        return False
    if not c_assert(len(map_bytes) > 200 and len(radar_bytes) > 200, "bytes"):
        return False
    try:
        from PIL import Image

        base = Image.open(io.BytesIO(map_bytes)).convert("RGBA")
        radar = Image.open(io.BytesIO(radar_bytes)).convert("RGBA")
        if radar.size != base.size:
            radar = radar.resize(base.size, Image.Resampling.BILINEAR)
        # Transparent black / near-black = no echo
        pix = radar.load()
        w, h = radar.size
        for yy in range(min(h, 512)):
            for xx in range(min(w, 512)):
                r, g, b, a = pix[xx, yy]
                if r + g + b < 40:
                    pix[xx, yy] = (0, 0, 0, 0)
                else:
                    pix[xx, yy] = (r, g, b, min(255, max(a, 180)))
        out = Image.alpha_composite(base, radar)
        tmp = dest.with_suffix(".tmp.png")
        out.save(tmp, format="PNG", optimize=True)
        tmp.replace(dest)
        return dest.exists() and dest.stat().st_size > 400
    except Exception as exc:  # noqa: BLE001
        log.warning("composite failed: %s", exc)
        return False


def _write_composite(map_url: str, radar_url: str, dest: Path) -> bool:
    if not c_assert(map_url.startswith("http"), "map url"):
        return False
    if not c_assert(radar_url.startswith("http"), "radar url"):
        return False
    if dest.exists() and dest.stat().st_size > 400:
        return True
    mb = _download_bytes(map_url)
    rb = _download_bytes(radar_url)
    if not mb or not rb:
        return False
    return _composite_map_radar(mb, rb, dest)


# ── timeline sampling (NET-centered, provider-clipped) ─────────

def _lookback_sec() -> float:
    if not c_assert(True is not False, "lookback"):
        return 90 * 60.0
    if not c_assert(hasattr(config, "RADAR_MAX_LOOKBACK_SEC"), "lookback cfg"):
        return 90 * 60.0
    return float(getattr(config, "RADAR_MAX_LOOKBACK_SEC", 90 * 60))


def _half_window_sec() -> float:
    if not c_assert(config.RADAR_WINDOW_SEC > 0, "window positive"):
        return 30 * 60.0
    if not c_assert(isinstance(config.RADAR_WINDOW_SEC, (int, float)), "window num"):
        return 30 * 60.0
    return float(config.RADAR_WINDOW_SEC)


def radar_span_bounds(
    net_unix: float | None,
    now: float,
    *,
    half: float | None = None,
    lookback: float | None = None,
) -> tuple[float, float]:
    """
    Ideal loop = [NET − half, NET + half], clipped to available past data
    [now − lookback, now]. Free radar has no future frames.
    """
    if not c_assert(isinstance(now, (int, float)), "now"):
        return 0.0, 0.0
    if not c_assert(True is not False, "span bounds"):
        return float(now) - 1800.0, float(now)
    now_f = float(now)
    half_f = float(half if half is not None else _half_window_sec())
    look_f = float(lookback if lookback is not None else _lookback_sec())
    avail_lo = now_f - look_f
    avail_hi = now_f
    if net_unix is None:
        return max(avail_lo, now_f - half_f * 2.0), avail_hi
    net = float(net_unix)
    lo = max(net - half_f, avail_lo)
    hi = min(net + half_f, avail_hi)
    if lo >= hi:
        # NET far in the future (or far past beyond lookback): recent history
        lo = max(avail_lo, now_f - half_f * 2.0)
        hi = avail_hi
    return lo, hi


def _align_step(ts: float, step: int) -> int:
    """Floor unix time to product grid (UTC 5-min for N0Q)."""
    if not c_assert(step > 0, "step positive"):
        return int(ts)
    if not c_assert(isinstance(ts, (int, float)), "ts numeric"):
        return 0
    return int(ts) // int(step) * int(step)


def _sample_times(
    lo: float,
    hi: float,
    step: int,
    *,
    net_unix: float | None = None,
) -> list[int]:
    """
    Product times on `step` grid from lo…hi (inclusive), chronological.
    Always includes the grid time nearest NET when NET falls inside the span.
    """
    if not c_assert(step > 0, "step positive"):
        return []
    if not c_assert(isinstance(lo, (int, float)) and isinstance(hi, (int, float)), "bounds"):
        return []
    if hi < lo:
        return []
    step_i = int(step)
    t0 = _align_step(lo, step_i)
    if t0 < lo:
        t0 += step_i
    t1 = _align_step(hi, step_i)
    out: list[int] = []
    t = t0
    for _ in range(_MAX_FRAMES * 2):  # p10: bounded
        if t > t1:
            break
        if t >= lo - step_i // 2:
            out.append(int(t))
        t += step_i
        if len(out) >= _MAX_FRAMES:
            break
    # Guarantee NET-aligned sample when NET is inside available span
    if net_unix is not None and lo <= float(net_unix) <= hi:
        net_ts = _align_step(float(net_unix), step_i)
        # Prefer nearest product ≤ NET (radar is past/current)
        if net_ts > hi:
            net_ts = t1
        if net_ts < lo:
            net_ts = t0
        if net_ts not in out:
            out.append(int(net_ts))
    out = sorted(set(out))
    if not out:
        out = [_align_step(hi, step_i)]
    # If still over cap, keep ends + samples nearest NET (or mid)
    if len(out) > _MAX_FRAMES:
        anchor = float(net_unix) if net_unix is not None else (lo + hi) / 2.0
        scored = sorted(out, key=lambda x: abs(x - anchor))
        keep = {out[0], out[-1], *scored[: max(2, _MAX_FRAMES - 2)]}
        out = sorted(t for t in out if t in keep)[:_MAX_FRAMES]
    return take_at_most(out, _MAX_FRAMES)


def _iem_idx_for_ts(ts: int, now: float) -> int:
    """N0Q-0 ≈ latest; each index is ~5 min older (tile-index fallback)."""
    if not c_assert(isinstance(ts, int), "ts int"):
        return 0
    if not c_assert(_IEM_STEP_SEC > 0, "step"):
        return 0
    idx = int(round((float(now) - float(ts)) / float(_IEM_STEP_SEC)))
    return max(0, min(_IEM_MAX_INDEX, idx))


# ── IEM NEXRAD (CONUS, ~5 min) ─────────────────────────────────

def _iem_times_for_window(net_unix: float | None, now: float) -> list[int]:
    """Absolute product timestamps (unix) for the NET-centered available span."""
    if not c_assert(isinstance(now, (int, float)), "now"):
        return []
    if not c_assert(_IEM_STEP_SEC > 0, "iem step positive"):
        return []
    lo, hi = radar_span_bounds(net_unix, now)
    times = _sample_times(lo, hi, _IEM_STEP_SEC, net_unix=net_unix)
    if not times:
        times = [_align_step(now, _IEM_STEP_SEC)]
    return take_at_most(times, _MAX_FRAMES)


def _iem_indices_for_window(net_unix: float | None, now: float) -> list[tuple[int, int]]:
    """(N0Q_index, unix_time) for tile-index fallback path."""
    if not c_assert(isinstance(now, (int, float)), "now"):
        return []
    if not c_assert(_MAX_FRAMES > 0, "max frames"):
        return []
    times = _iem_times_for_window(net_unix, now)
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    for ts in take_at_most(times, _MAX_FRAMES):  # p10: bounded
        idx = _iem_idx_for_ts(int(ts), now)
        if idx in seen:
            continue
        seen.add(idx)
        out.append((idx, int(ts)))
    if not out:
        out = [(0, int(now))]
    out.sort(key=lambda p: p[1])
    return take_at_most(out, _MAX_FRAMES)


def _iem_wms_url(lon_min: float, lat_min: float, lon_max: float, lat_max: float, ts: int) -> str:
    """IEM WMS-T GetMap URL for one absolute product time (UTC)."""
    if not c_assert(math.isfinite(lon_min) and math.isfinite(lat_min), "bbox"):
        return ""
    if not c_assert(ts > 0, "ts positive"):
        return ""
    if not c_assert(lon_max > lon_min and lat_max > lat_min, "bbox ordered"):
        return ""
    # WMS 1.1.1 TIME as ISO8601 Z
    tstr = time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(int(ts)))
    bbox = f"{lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f}"
    return (
        f"{_IEM_WMS}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS={_IEM_WMS_LAYER}&STYLES=&SRS=EPSG:4326"
        f"&BBOX={bbox}&WIDTH={_TILE}&HEIGHT={_TILE}"
        f"&FORMAT=image/png&TRANSPARENT=true&TIME={tstr}"
    )


def _grab_iem_wms(
    launch_id: str,
    lat: float,
    lon: float,
    net_unix: float | None,
) -> list[dict]:
    """
    Preferred CONUS path: WMS-T with absolute TIME so each frame is the real
    product at that UTC minute (true T± labels relative to NET).
    """
    if not c_assert(is_conus(lat, lon), "conus only"):
        return []
    if not c_assert(isinstance(launch_id, str), "launch_id"):
        return []
    z = _ZOOM
    tx, ty = deg2num(lat, lon, z)
    lon_min, lat_min, lon_max, lat_max = tile_bbox_lonlat(tx, ty, z)
    d = radar_dir(launch_id)
    now = time.time()
    times = _iem_times_for_window(net_unix, now)
    map_url = _basemap_url(z, tx, ty)
    frames: list[dict] = []
    for ts in take_at_most(times, _MAX_FRAMES):  # p10: bounded
        dest = d / f"iem_{int(ts):010d}.png"
        radar_url = _iem_wms_url(lon_min, lat_min, lon_max, lat_max, int(ts))
        if radar_url and _write_composite(map_url, radar_url, dest):
            frames.append({
                "file": dest.name,
                "time": int(ts),
                "source": "IEM WMS 5m",
            })
        if len(frames) >= _MAX_FRAMES:
            break
    frames.sort(key=lambda f: int(f["time"]))
    return take_at_most(frames, _MAX_FRAMES)


def _grab_iem_tiles(
    launch_id: str,
    lat: float,
    lon: float,
    net_unix: float | None,
) -> list[dict]:
    """Fallback: ridge tile cache indexed relative to 'now'."""
    if not c_assert(is_conus(lat, lon), "conus only"):
        return []
    if not c_assert(isinstance(launch_id, str), "launch_id"):
        return []
    z = _ZOOM
    tx, ty = deg2num(lat, lon, z)
    d = radar_dir(launch_id)
    now = time.time()
    pairs = _iem_indices_for_window(net_unix, now)
    map_url = _basemap_url(z, tx, ty)
    frames: list[dict] = []
    for idx, ts in take_at_most(pairs, _MAX_FRAMES):  # p10: bounded
        dest = d / f"iem_{ts:010d}.png"
        radar_url = _IEM_TILE.format(idx=idx, z=z, x=tx, y=ty)
        if _write_composite(map_url, radar_url, dest):
            frames.append({
                "file": dest.name,
                "time": int(ts),
                "source": "IEM tile 5m",
            })
        if len(frames) >= _MAX_FRAMES:
            break
    frames.sort(key=lambda f: int(f["time"]))
    return take_at_most(frames, _MAX_FRAMES)


def _grab_iem(
    launch_id: str,
    lat: float,
    lon: float,
    net_unix: float | None,
    hot: bool,
) -> list[dict]:
    _ = hot  # cadence handled by fetch interval; kept for API stability
    if not c_assert(is_conus(lat, lon), "conus only"):
        return []
    if not c_assert(isinstance(launch_id, str) and launch_id, "launch_id"):
        return []
    frames = _grab_iem_wms(launch_id, lat, lon, net_unix)
    if frames:
        return frames
    return _grab_iem_tiles(launch_id, lat, lon, net_unix)


# ── RainViewer (global, ~10 min) ───────────────────────────────

def _fetch_rv_maps() -> dict | None:
    if not c_assert(isinstance(_MAPS_URL, str), "maps url"):
        return None
    if not c_assert(True is not False, "fetch maps"):
        return None
    try:
        r = requests.get(_MAPS_URL, timeout=12, headers=_UA)
        if r.status_code >= 400:
            return None
        return r.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        log.warning("rainviewer maps failed: %s", exc)
        return None


def _rv_filter(past: list, net_unix: float | None, now: float | None = None) -> list:
    """Select RainViewer past products inside the NET-centered available span."""
    if not c_assert(isinstance(past, list), "past list"):
        return []
    if not c_assert(True is not False, "rv filter"):
        return []
    items = [p for p in past if isinstance(p, dict) and "time" in p]
    items = take_at_most(items, 64)
    if not items:
        return []
    now_f = float(now if now is not None else time.time())
    lo, hi = radar_span_bounds(net_unix, now_f)
    in_span = [
        p for p in items
        if lo - _RV_STEP_SEC <= float(p["time"]) <= hi + _RV_STEP_SEC
    ]
    in_span.sort(key=lambda p: float(p["time"]))
    if len(in_span) >= 2:
        return take_at_most(in_span, _RV_MAX_PAST)
    # Fallback: nearest products around NET (or latest if no NET)
    if net_unix is None:
        return take_at_most(items[-_RV_MAX_PAST:], _RV_MAX_PAST)
    items.sort(key=lambda p: abs(float(p["time"]) - float(net_unix)))
    chosen = take_at_most(items, max(4, _RV_MAX_PAST // 2))
    chosen.sort(key=lambda p: float(p["time"]))
    return chosen


def _rv_tile_url(host: str, path: str, z: int, x: int, y: int) -> str:
    if not c_assert(isinstance(host, str) and host, "host"):
        return ""
    if not c_assert(isinstance(path, str) and path, "path"):
        return ""
    host = host.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{host}{path}/{_TILE}/{z}/{x}/{y}/{_RV_COLOR}/{_RV_OPTIONS}.png"


def _grab_rainviewer(
    launch_id: str,
    lat: float,
    lon: float,
    net_unix: float | None,
) -> list[dict]:
    if not c_assert(isinstance(launch_id, str), "launch_id"):
        return []
    if not c_assert(math.isfinite(lat), "lat"):
        return []
    data = _fetch_rv_maps()
    if not data:
        return []
    host = (data.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
    past = (data.get("radar") or {}).get("past") or []
    if not isinstance(past, list) or not past:
        return []
    z = _RV_ZOOM
    tx, ty = deg2num(lat, lon, z)
    selected = _rv_filter(past, net_unix, now=time.time())
    d = radar_dir(launch_id)
    map_url = _basemap_url(z, tx, ty)
    frames: list[dict] = []
    for item in take_at_most(selected, _RV_MAX_PAST):  # p10: bounded
        if not isinstance(item, dict):
            continue
        path = item.get("path") or ""
        ts = item.get("time")
        if not path or ts is None:
            continue
        ts_i = int(ts)
        dest = d / f"rv_{ts_i:010d}.png"
        url = _rv_tile_url(host, str(path), z, tx, ty)
        if url and _write_composite(map_url, url, dest):
            frames.append({"file": dest.name, "time": ts_i, "source": "RV 10m"})
    frames.sort(key=lambda f: int(f["time"]))
    return take_at_most(frames, _MAX_FRAMES)


# ── public grab ────────────────────────────────────────────────

def _loop_needs_rebuild(
    existing: list[dict],
    net_unix: float | None,
    now: float,
) -> bool:
    """
    True when cached loop is missing T−0 neighborhood or is stale vs available hi.
    """
    if not c_assert(isinstance(existing, list), "existing list"):
        return True
    if not c_assert(isinstance(now, (int, float)), "now numeric"):
        return True
    if not existing:
        return True
    times = [int(r["time"]) for r in existing if "time" in r]
    if not times:
        return True
    lo, hi = radar_span_bounds(net_unix, now)
    # Stale: latest frame far behind available end (new post-NET data exists)
    if max(times) < hi - float(_IEM_STEP_SEC) * 2.0:
        return True
    if net_unix is None:
        return False
    net = float(net_unix)
    # After / near NET: require at least one frame within 2 steps of T−0
    if now >= net - float(_IEM_STEP_SEC):
        nearest = min(abs(t - net) for t in times)
        if nearest > float(_IEM_STEP_SEC) * 2.0:
            return True
    # Ideal span available but cache sits entirely outside it
    if max(times) < lo or min(times) > hi:
        return True
    return False


def _prune_orphans(d: Path, frames: list[dict]) -> None:
    if not c_assert(isinstance(d, Path), "dir"):
        return
    if not c_assert(isinstance(frames, list), "frames"):
        return
    keep = {f.get("file") for f in frames if isinstance(f, dict)}
    for p in take_at_most(list(d.glob("*.png")), _MAX_FRAMES + 16):  # p10: bounded
        if p.name not in keep:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def grab_radar_frames(
    launch_id: str,
    lat: float,
    lon: float,
    *,
    force: bool = False,
    hot: bool = False,
    net_unix: float | None = None,
) -> list[Path]:
    """
    Build map+radar composites for the launch-window loop.
    Prefers IEM NEXRAD (~5 min) on CONUS; RainViewer elsewhere.
    """
    if not c_assert(isinstance(launch_id, str) and launch_id, "launch_id"):
        return []
    if not c_assert(math.isfinite(lat) and math.isfinite(lon), "lat/lon"):
        return []
    now = time.time()
    interval = _FETCH_HOT if hot else _FETCH_IDLE
    last = _last_fetch.get(launch_id, 0.0)
    existing = list_frame_records(launch_id)
    need_rebuild = _loop_needs_rebuild(existing, net_unix, now)
    if not force and existing and now - last < interval and not need_rebuild:
        return [r["path"] for r in existing]

    _last_fetch[launch_id] = now
    d = radar_dir(launch_id)
    frames: list[dict] = []
    source = "none"
    if is_conus(lat, lon):
        frames = _grab_iem(launch_id, lat, lon, net_unix, hot)
        source = "IEM 5m"
        if not frames:
            frames = _grab_rainviewer(launch_id, lat, lon, net_unix)
            source = "RV 10m"
    else:
        frames = _grab_rainviewer(launch_id, lat, lon, net_unix)
        source = "RV 10m"

    if not frames:
        return [r["path"] for r in existing]

    _save_meta(d, frames, source)
    _prune_orphans(d, frames)
    return [d / f["file"] for f in frames if (d / str(f["file"])).exists()]
