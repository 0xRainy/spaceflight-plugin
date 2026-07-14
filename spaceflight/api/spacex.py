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

log = logging.getLogger("spaceflight.api.spacex")

CMS = "https://content.spacex.com"
API = f"{CMS}/api/spacex-website"
PAGE_BASE = "https://www.spacex.com/launches"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }
    )
    return s


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _media_url(obj: dict | None) -> str:
    if not obj or not isinstance(obj, dict):
        return ""
    return obj.get("url") or ""


def _parse_timeline_block(block: dict | None, *, phase: str, sign: int) -> tuple[str, str, list[TimelineEvent]]:
    """
    sign=-1 for pre-launch (T-), +1 for post (T+).
    SpaceX stores absolute H:M:S from T-0 for both; we apply the sign.
    """
    if not block:
        return "", "", []
    title = block.get("title") or ""
    disclaimer = block.get("disclaimer") or ""
    events: list[TimelineEvent] = []
    for entry in block.get("timelineEntries") or []:
        raw_t = entry.get("time") or "00:00:00"
        secs = parse_hms_to_seconds(str(raw_t))
        if secs is None:
            continue
        # pre-launch entries are times BEFORE T-0 → negative relative
        rel = -secs if sign < 0 else secs
        # special: pre-launch "00:00:00 Excitement guaranteed" stays at 0
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
    return title, disclaimer, events


def parse_mission_payload(data: dict) -> MissionBrief:
    mid = data.get("missionId") or ""
    pre_title, pre_disc, countdown = _parse_timeline_block(
        data.get("preLaunchTimeline"), phase="countdown", sign=-1
    )
    post_title, post_disc, flight = _parse_timeline_block(
        data.get("postLaunchTimeline"), phase="flight", sign=+1
    )
    paragraphs = []
    for p in data.get("paragraphs") or []:
        if isinstance(p, dict):
            t = _strip_html(p.get("content") or "")
        else:
            t = _strip_html(str(p))
        if t:
            paragraphs.append(t)

    webcasts: list[StreamLink] = []
    for w in data.get("webcasts") or []:
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
    session = session or _session()
    try:
        r = session.get(f"{API}/launches-page-tiles/upcoming", timeout=25)
        if r.status_code != 200:
            log.warning("SpaceX upcoming tiles HTTP %s", r.status_code)
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except requests.RequestException as exc:
        log.warning("SpaceX tiles error: %s", exc)
        return []


def fetch_mission(slug: str, session: requests.Session | None = None) -> MissionBrief | None:
    if not slug:
        return None
    session = session or _session()
    try:
        r = session.get(f"{API}/missions/{slug}", timeout=25)
        if r.status_code != 200:
            log.info("SpaceX mission %s HTTP %s", slug, r.status_code)
            return None
        return parse_mission_payload(r.json())
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning("SpaceX mission %s failed: %s", slug, exc)
        return None


def guess_slug(L: Launch) -> str | None:
    """Heuristic slug from LL2 launch name."""
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
    if "tranche 1 transport" in blob or "sda" in blob and "transport layer" in blob:
        # letter suffix if present
        m = re.search(r"transport layer\s*([a-z])\b", blob)
        if m:
            return f"sda-t1tl-{m.group(1)}"
        return "sda-t1tl-e"

    if re.search(r"\bmrv\b", blob):
        if "mep" in blob:
            return "mrv-mep"
        return "mrv-1"

    return None


def match_tile(L: Launch, tiles: list[dict]) -> dict | None:
    """Match an LL2 launch to a SpaceX upcoming tile (strict — avoid wrong missions)."""
    if not tiles:
        return None
    vehicle = (L.vehicle.name or L.vehicle_name() or "").lower()
    short = (L.short_name() or "").lower()
    name = (L.name or "").lower()
    day = L.net.strftime("%Y-%m-%d") if L.net else ""

    best = None
    best_score = 0
    for t in tiles:
        score = 0
        title = (t.get("title") or "").lower()
        link = (t.get("link") or "").lower()
        tveh = (t.get("vehicle") or "").lower()
        tday = t.get("launchDate") or ""

        # Vehicle family
        if "starship" in name or "starship" in vehicle:
            if "starship" not in title and "starship" not in link:
                continue
            score += 4
        elif "falcon" in vehicle or "falcon" in name:
            if tveh and "falcon" not in tveh and "starship" in tveh:
                continue
            if tveh and "falcon" in tveh:
                score += 1

        # Exact / near date is strong signal
        if day and tday:
            if day == tday:
                score += 5
            else:
                try:
                    d0 = datetime.strptime(day, "%Y-%m-%d").date()
                    d1 = datetime.strptime(tday, "%Y-%m-%d").date()
                    delta = abs((d0 - d1).days)
                    if delta <= 1:
                        score += 3
                    elif delta > 3:
                        score -= 4  # wrong mission week
                except ValueError:
                    pass

        # Starlink group numbers must match
        if "starlink" in name or "starlink" in short:
            if "starlink" not in title and not link.startswith("sl-"):
                continue
            m = re.search(r"(\d+)[- ](\d+)", short)
            if m:
                needle = f"{m.group(1)}-{m.group(2)}"
                if needle in link or needle in title:
                    score += 8
                else:
                    score -= 6  # different Starlink group

        if "starship" in name:
            m = re.search(r"flight\s*(\d+)", name)
            if m and m.group(1) in link:
                score += 8

        # Distinctive tokens from short name (skip generic words)
        stop = {"mission", "group", "flight", "block", "test", "the", "and"}
        for token in re.findall(r"[a-z0-9]{3,}", short):
            if token in stop:
                continue
            if token in title or token in link:
                score += 2

        if score > best_score:
            best_score = score
            best = t
    # Require a confident match
    if best_score >= 6:
        return best
    return None


def enrich_launches(launches: list[Launch], max_missions: int = 10) -> int:
    """
    Attach SpaceX MissionBrief to matching launches.
    Returns number of launches enriched.
    """
    session = _session()
    tiles = fetch_upcoming_tiles(session)
    enriched = 0
    fetched_slugs: dict[str, MissionBrief | None] = {}
    used_slugs: set[str] = set()

    # Prefer soonest *upcoming* SpaceX launches
    now = datetime.now(timezone.utc)
    candidates = []
    for L in launches:
        if not (
            "spacex" in (L.provider or "").lower()
            or "falcon" in (L.vehicle.name or "").lower()
            or "starship" in (L.vehicle.name or L.name or "").lower()
        ):
            continue
        # Skip long-finished flights for CMS enrichment
        secs = L.seconds_to_net(now)
        if secs is not None and secs < -3600:
            continue
        candidates.append(L)

    def sk(L: Launch):
        s = L.seconds_to_net(now)
        return s if s is not None else 10**12

    candidates.sort(key=sk)

    for L in candidates:
        if enriched >= max_missions:
            break
        # Prefer CMS tile link (canonical) when match is confident; else name guess
        tile = match_tile(L, tiles)
        slug = (tile.get("link") if tile else None) or guess_slug(L)
        if not slug:
            continue
        # One slug → one launch (soonest first already sorted)
        if slug in used_slugs and guess_slug(L) != slug:
            continue
        if slug not in fetched_slugs:
            fetched_slugs[slug] = fetch_mission(slug, session)
        brief = fetched_slugs[slug]
        if not brief:
            continue
        used_slugs.add(slug)
        L.mission_brief = brief
        # Merge streams from SpaceX webcasts if we lack them
        if brief.webcasts and not L.streams:
            L.streams = list(brief.webcasts)
        elif brief.webcasts:
            existing = {s.url for s in L.streams}
            for s in brief.webcasts:
                if s.url not in existing:
                    L.streams.append(s)
        if brief.page_url and brief.page_url not in L.info_urls:
            L.info_urls.insert(0, brief.page_url)
        if brief.all_events():
            L.timeline = brief.all_events()
        if brief.hero_image_url and not L.image_url:
            L.image_url = brief.hero_image_url
        enriched += 1
        log.info("Enriched %s → SpaceX %s (%d events)", L.name, slug, len(brief.all_events()))

    return enriched
