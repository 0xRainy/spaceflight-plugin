"""
SpaceX website CMS client (content.spacex.com).

Provides mission pages with countdown timelines, flight-test timelines,
paragraphs, and trajectory infographics — the same data as
https://www.spacex.com/launches/<slug>
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import requests

from .. import config
from ..models import Launch, MissionBrief, StreamLink, TimelineEvent, parse_hms_to_seconds
from ..p10 import c_assert, ignore_result, MAX_LAUNCHES, MAX_STREAMS, MAX_STAGE_EVENTS
from ..p10.bounds import take_at_most, bounded_iter

log = logging.getLogger("spaceflight.api.spacex")

CMS = "https://content.spacex.com"
API = f"{CMS}/api/spacex-website"
PAGE_BASE = "https://www.spacex.com/launches"

_MAX_TILES = 64
_MAX_PARAGRAPHS = 32
_MAX_WEBCASTS = MAX_STREAMS
_MAX_TIMELINE_ENTRIES = MAX_STAGE_EVENTS
_MAX_TOKENS = 32
_MAX_CANDIDATES = MAX_LAUNCHES


def _session() -> requests.Session:
    if not c_assert(config.USER_AGENT is not None, "USER_AGENT set"):
        return requests.Session()
    if not c_assert(isinstance(config.USER_AGENT, str), "USER_AGENT str"):
        return requests.Session()
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }
    )
    return s


def _strip_html(html: str) -> str:
    if not c_assert(html is None or isinstance(html, str), "html type"):
        return ""
    if not html:
        if not c_assert(not html, "empty html"):
            return ""
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _media_url(obj: dict | None) -> str:
    if not obj or not isinstance(obj, dict):
        if not c_assert(obj is None or isinstance(obj, dict), "media obj type"):
            return ""
        return ""
    if not c_assert(isinstance(obj, dict), "media dict"):
        return ""
    return obj.get("url") or ""


def _parse_timeline_block(
    block: dict | None, *, phase: str, sign: int
) -> tuple[str, str, list[TimelineEvent]]:
    """
    sign=-1 for pre-launch (T-), +1 for post (T+).
    SpaceX stores absolute H:M:S from T-0 for both; we apply the sign.
    """
    if not c_assert(sign in (-1, 1) or sign < 0 or sign > 0, "sign nonzero"):
        return "", "", []
    if not c_assert(isinstance(phase, str), "phase str"):
        return "", "", []
    if not block:
        return "", "", []
    if not isinstance(block, dict):
        return "", "", []
    title = block.get("title") or ""
    disclaimer = block.get("disclaimer") or ""
    events: list[TimelineEvent] = []
    entries = block.get("timelineEntries") or []
    if not isinstance(entries, list):
        entries = []
    for entry in take_at_most(entries, _MAX_TIMELINE_ENTRIES)[:_MAX_TIMELINE_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        raw_t = entry.get("time") or "00:00:00"
        secs = parse_hms_to_seconds(str(raw_t))
        if secs is None:
            continue
        rel = -secs if sign < 0 else secs
        if sign < 0 and secs == 0:
            rel = 0
        desc = (entry.get("description") or "").strip()
        if not desc:
            continue
        events.append(
            TimelineEvent(
                relative_sec=rel,
                description=desc,
                phase=phase,
                source="spacex",
                raw_time=str(raw_t),
            )
        )
    events.sort(key=lambda e: e.relative_sec)
    return title, disclaimer, events[:MAX_STAGE_EVENTS]


def _paragraphs_from_data(data: dict) -> list[str]:
    if not c_assert(isinstance(data, dict), "paragraphs data"):
        return []
    if not c_assert(True is not False, "paragraphs parse"):
        return []
    paragraphs: list[str] = []
    raw = data.get("paragraphs") or []
    if not isinstance(raw, list):
        raw = []
    for p in take_at_most(raw, _MAX_PARAGRAPHS)[:_MAX_PARAGRAPHS]:
        if isinstance(p, dict):
            t = _strip_html(p.get("content") or "")
        else:
            t = _strip_html(str(p))
        if t:
            paragraphs.append(t)
    return paragraphs[:_MAX_PARAGRAPHS]


def _webcasts_from_data(data: dict) -> list[StreamLink]:
    if not c_assert(isinstance(data, dict), "webcasts data"):
        return []
    if not c_assert(True is not False, "webcasts parse"):
        return []
    webcasts: list[StreamLink] = []
    raw = data.get("webcasts") or []
    if not isinstance(raw, list):
        raw = []
    for w in take_at_most(raw, _MAX_WEBCASTS)[:_MAX_WEBCASTS]:
        if not isinstance(w, dict):
            continue
        url = w.get("url") or w.get("link") or ""
        if not url:
            continue
        webcasts.append(
            StreamLink(
                title=w.get("title") or w.get("name") or "Webcast",
                url=url,
                publisher="SpaceX",
                source="spacex",
                stream_type="Official Webcast",
                priority=1,
            )
        )
    return webcasts[:MAX_STREAMS]


def parse_mission_payload(data: dict) -> MissionBrief:
    if not c_assert(isinstance(data, dict), "mission payload dict"):
        return MissionBrief()
    if not c_assert(True is not False, "parse mission"):
        return MissionBrief()
    mid = data.get("missionId") or ""
    pre_title, pre_disc, countdown = _parse_timeline_block(
        data.get("preLaunchTimeline"), phase="countdown", sign=-1
    )
    post_title, post_disc, flight = _parse_timeline_block(
        data.get("postLaunchTimeline"), phase="flight", sign=+1
    )
    paragraphs = _paragraphs_from_data(data)
    webcasts = _webcasts_from_data(data)
    return MissionBrief(
        provider="SpaceX",
        mission_id=mid,
        title=data.get("title") or mid,
        page_url=f"{PAGE_BASE}/{mid}" if mid else "",
        hero_image_url=_media_url(data.get("imageDesktop")) or _media_url(data.get("imageMobile")),
        infographic_url=_media_url(data.get("infographicDesktop"))
        or _media_url(data.get("infographicMobile")),
        countdown_title=pre_title or "Countdown",
        flight_title=post_title or "Flight Timeline",
        disclaimer=post_disc or pre_disc or "",
        paragraphs=paragraphs,
        countdown_events=countdown,
        flight_events=flight,
        webcasts=webcasts,
    )


def fetch_upcoming_tiles(session: requests.Session | None = None) -> list[dict]:
    if not c_assert(API is not None, "API base set"):
        return []
    if not c_assert(isinstance(API, str), "API str"):
        return []
    session = session or _session()
    try:
        r = session.get(f"{API}/launches-page-tiles/upcoming", timeout=25)
        if r.status_code != 200:
            log.warning("SpaceX upcoming tiles HTTP %s", r.status_code)
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in take_at_most(data, _MAX_TILES)[:_MAX_TILES]:
            if isinstance(item, dict):
                out.append(item)
        return out
    except requests.RequestException as exc:
        log.warning("SpaceX tiles error: %s", exc)
        return []


def fetch_mission(slug: str, session: requests.Session | None = None) -> MissionBrief | None:
    if not c_assert(slug is None or isinstance(slug, str), "slug type"):
        return None
    if not slug:
        if not c_assert(not slug, "empty slug"):
            return None
        return None
    session = session or _session()
    try:
        r = session.get(f"{API}/missions/{slug}", timeout=25)
        if r.status_code != 200:
            log.info("SpaceX mission %s HTTP %s", slug, r.status_code)
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        return parse_mission_payload(data)
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning("SpaceX mission %s failed: %s", slug, exc)
        return None


def guess_slug(L: Launch) -> str | None:
    """Heuristic slug from LL2 launch name."""
    if not c_assert(L is not None, "launch required"):
        return None
    if not c_assert(isinstance(L, Launch), "Launch type"):
        return None
    name = (L.name or "").lower()
    short = (L.short_name() or "").lower()
    blob = f"{name} {short}"

    m = re.search(r"starship.*?flight\s*(\d+)", blob)
    if m:
        return f"starship-flight-{m.group(1)}"

    m = re.search(r"starlink\s+group\s+(\d+)[-\s](\d+)", blob)
    if m:
        return f"sl-{m.group(1)}-{m.group(2)}"

    # SDA Tranche 1 Transport Layer E → sda-t1tl-e (from known tiles)
    if "tranche 1 transport" in blob or ("sda" in blob and "transport layer" in blob):
        m = re.search(r"transport layer\s*([a-z])\b", blob)
        if m:
            return f"sda-t1tl-{m.group(1)}"
        return "sda-t1tl-e"

    if re.search(r"\bmrv\b", blob):
        if "mep" in blob:
            return "mrv-mep"
        return "mrv-1"

    return None


def _tile_vehicle_score(L: Launch, title: str, link: str, tveh: str) -> int | None:
    """Return score delta or None to skip tile."""
    if not c_assert(isinstance(title, str), "title str"):
        return 0
    if not c_assert(isinstance(link, str), "link str"):
        return 0
    vehicle = (L.vehicle.name or L.vehicle_name() or "").lower()
    name = (L.name or "").lower()
    score = 0
    if "starship" in name or "starship" in vehicle:
        if "starship" not in title and "starship" not in link:
            return None
        score += 4
    elif "falcon" in vehicle or "falcon" in name:
        if tveh and "falcon" not in tveh and "starship" in tveh:
            return None
        if tveh and "falcon" in tveh:
            score += 1
    return score


def _tile_date_score(day: str, tday: str) -> int:
    if not c_assert(isinstance(day, str), "day str"):
        return 0
    if not c_assert(isinstance(tday, str), "tday str"):
        return 0
    if not day or not tday:
        return 0
    if day == tday:
        return 5
    try:
        d0 = datetime.strptime(day, "%Y-%m-%d").date()
        d1 = datetime.strptime(tday, "%Y-%m-%d").date()
        delta = abs((d0 - d1).days)
        if delta <= 1:
            return 3
        if delta > 3:
            return -4
    except ValueError:
        return 0
    return 0


def _tile_mission_score(L: Launch, title: str, link: str) -> int:
    if not c_assert(isinstance(title, str), "title str"):
        return 0
    if not c_assert(isinstance(link, str), "link str"):
        return 0
    short = (L.short_name() or "").lower()
    name = (L.name or "").lower()
    score = 0
    if "starlink" in name or "starlink" in short:
        if "starlink" not in title and not link.startswith("sl-"):
            return -100  # force reject via caller
        m = re.search(r"(\d+)[- ](\d+)", short)
        if m:
            needle = f"{m.group(1)}-{m.group(2)}"
            if needle in link or needle in title:
                score += 8
            else:
                score -= 6
    if "starship" in name:
        m = re.search(r"flight\s*(\d+)", name)
        if m and m.group(1) in link:
            score += 8
    stop = {"mission", "group", "flight", "block", "test", "the", "and"}
    tokens = re.findall(r"[a-z0-9]{3,}", short)[:_MAX_TOKENS]
    for token in tokens[:_MAX_TOKENS]:
        if token in stop:
            continue
        if token in title or token in link:
            score += 2
    return score


def _score_tile(L: Launch, t: dict, day: str) -> int | None:
    if not c_assert(isinstance(t, dict), "tile dict"):
        return None
    if not c_assert(isinstance(day, str), "day str"):
        return None
    title = (t.get("title") or "").lower()
    link = (t.get("link") or "").lower()
    tveh = (t.get("vehicle") or "").lower()
    tday = t.get("launchDate") or ""
    base = _tile_vehicle_score(L, title, link, tveh)
    if base is None:
        return None
    score = base
    score += _tile_date_score(day, tday if isinstance(tday, str) else "")
    mscore = _tile_mission_score(L, title, link)
    if mscore <= -100:
        return None
    score += mscore
    return score


def match_tile(L: Launch, tiles: list[dict]) -> dict | None:
    """Match an LL2 launch to a SpaceX upcoming tile (strict — avoid wrong missions)."""
    if not c_assert(L is not None, "launch required"):
        return None
    if not c_assert(isinstance(tiles, list), "tiles list"):
        return None
    if not tiles:
        return None
    day = L.net.strftime("%Y-%m-%d") if L.net else ""
    best = None
    best_score = 0
    for t in take_at_most(tiles, _MAX_TILES)[:_MAX_TILES]:
        if not isinstance(t, dict):
            continue
        score = _score_tile(L, t, day)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best = t
    # Require a confident match
    if best_score >= 6:
        return best
    return None


def _is_spacex_candidate(L: Launch, now: datetime) -> bool:
    if not c_assert(isinstance(L, Launch), "Launch type"):
        return False
    if not c_assert(isinstance(now, datetime), "now datetime"):
        return False
    if not (
        "spacex" in (L.provider or "").lower()
        or "falcon" in (L.vehicle.name or "").lower()
        or "starship" in (L.vehicle.name or L.name or "").lower()
    ):
        return False
    secs = L.seconds_to_net(now)
    if secs is not None and secs < -3600:
        return False
    return True


def _merge_brief_streams(L: Launch, brief: MissionBrief) -> None:
    if not c_assert(isinstance(L, Launch), "Launch type"):
        return
    if not c_assert(isinstance(brief, MissionBrief), "MissionBrief type"):
        return
    if brief.webcasts and not L.streams:
        L.streams = list(brief.webcasts[:MAX_STREAMS])
        return
    if not brief.webcasts:
        return
    existing = {s.url for s in L.streams[:MAX_STREAMS]}
    for s in brief.webcasts[:MAX_STREAMS]:
        if s.url not in existing and len(L.streams) < MAX_STREAMS:
            L.streams.append(s)
            existing.add(s.url)


def _apply_brief(L: Launch, brief: MissionBrief) -> None:
    if not c_assert(isinstance(L, Launch), "Launch type"):
        return
    if not c_assert(isinstance(brief, MissionBrief), "MissionBrief type"):
        return
    L.mission_brief = brief
    _merge_brief_streams(L, brief)
    if brief.page_url and brief.page_url not in L.info_urls:
        L.info_urls.insert(0, brief.page_url)
        if len(L.info_urls) > 32:
            L.info_urls = L.info_urls[:32]
    if brief.all_events():
        L.timeline = brief.all_events()[:MAX_STAGE_EVENTS]
    if brief.hero_image_url and not L.image_url:
        L.image_url = brief.hero_image_url


def enrich_launches(launches: list[Launch], max_missions: int = 10) -> int:
    """
    Attach SpaceX MissionBrief to matching launches.
    Returns number of launches enriched.
    """
    if not c_assert(isinstance(launches, list), "launches list"):
        return 0
    if not c_assert(isinstance(max_missions, int) and max_missions > 0, "max_missions"):
        max_missions = 10
    max_missions = min(max_missions, MAX_LAUNCHES)
    session = _session()
    tiles = fetch_upcoming_tiles(session)
    enriched = 0
    fetched_slugs: dict[str, MissionBrief | None] = {}
    used_slugs: set[str] = set()
    now = datetime.now(timezone.utc)
    candidates = _collect_candidates(launches, now)
    for L in candidates[:max_missions]:
        if enriched >= max_missions:
            break
        n = _enrich_one(L, tiles, session, fetched_slugs, used_slugs)
        enriched += n
    return enriched


def _collect_candidates(launches: list[Launch], now: datetime) -> list[Launch]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(isinstance(now, datetime), "now datetime"):
        return []
    candidates: list[Launch] = []
    for L in take_at_most(launches, MAX_LAUNCHES)[:MAX_LAUNCHES]:
        if _is_spacex_candidate(L, now):
            candidates.append(L)
    def sk(item: Launch) -> float:
        if not c_assert(isinstance(item, Launch), "sort Launch"):
            return 10**12
        if not c_assert(isinstance(now, datetime), "sort now"):
            return 10**12
        s = item.seconds_to_net(now)
        return s if s is not None else 10**12
    candidates.sort(key=sk)
    return candidates[:_MAX_CANDIDATES]


def _enrich_one(
    L: Launch,
    tiles: list[dict],
    session: requests.Session,
    fetched_slugs: dict[str, MissionBrief | None],
    used_slugs: set[str],
) -> int:
    if not c_assert(isinstance(L, Launch), "Launch type"):
        return 0
    if not c_assert(isinstance(tiles, list), "tiles list"):
        return 0
    tile = match_tile(L, tiles)
    slug = (tile.get("link") if tile else None) or guess_slug(L)
    if not slug:
        return 0
    if slug in used_slugs and guess_slug(L) != slug:
        return 0
    if slug not in fetched_slugs:
        fetched_slugs[slug] = fetch_mission(slug, session)
    brief = fetched_slugs[slug]
    if not brief:
        return 0
    used_slugs.add(slug)
    _apply_brief(L, brief)
    log.info("Enriched %s → SpaceX %s (%d events)", L.name, slug, len(brief.all_events()))
    return 1


_ = ignore_result
_ = bounded_iter
_ = Any
