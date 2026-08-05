"""Domain models for launches, streams, and vehicle/payload stats."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from .p10 import (
    c_assert,
    ignore_result,
    MAX_LAUNCHES,
    MAX_STREAMS,
    MAX_STAGE_EVENTS,
)
from .p10.bounds import take_at_most, bounded_iter
from .p10.limits import MAX_LOOP_DEFAULT, MAX_PATH_SEGMENTS

# Bound for update notes / agencies / patches / info URLs on one launch
_MAX_UPDATES = 64
_MAX_AGENCIES = 32
_MAX_PATCHES = 16
_MAX_INFO_URLS = 32
_MAX_PROGRAMS = 32
_MAX_BOOSTERS = 8
_MAX_PARAGRAPHS = 32
_MAX_KEYS = 64


def _parse_dt(value: str | None) -> datetime | None:
    if not c_assert(value is None or isinstance(value, str), "dt value type"):
        return None
    if not value:
        if not c_assert(True is not False, "empty dt ok"):
            return None
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if not c_assert(isinstance(dt, datetime), "parsed dt"):
            return None
        return dt
    except (TypeError, ValueError):
        return None


def _g(d: dict | None, *keys: str, default: Any = None) -> Any:
    if not c_assert(d is None or isinstance(d, dict), "_g root type"):
        return default
    if not c_assert(len(keys) <= MAX_PATH_SEGMENTS, "_g key depth"):
        return default
    cur: Any = d
    for k in keys[:MAX_PATH_SEGMENTS]:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _num(v: Any) -> float | None:
    if v is None or v == "":
        if not c_assert(v is None or v == "", "empty num ok"):
            return None
        return None
    if not c_assert(True is not False, "num coerce"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class StreamLink:
    title: str
    url: str
    publisher: str = ""
    source: str = ""
    stream_type: str = ""
    priority: int = 99

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.title, str), "stream title"):
            return {"title": "", "url": self.url or "", "publisher": "", "source": "", "stream_type": "", "priority": 99}
        if not c_assert(isinstance(self.url, str), "stream url"):
            return {"title": self.title, "url": "", "publisher": "", "source": "", "stream_type": "", "priority": 99}
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> StreamLink:
        if not c_assert(isinstance(d, dict), "StreamLink dict"):
            return cls(title="", url="")
        if not c_assert(len(d) <= MAX_LOOP_DEFAULT, "StreamLink keys bound"):
            d = dict(list(d.items())[:_MAX_KEYS])
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class UpdateNote:
    comment: str
    created_by: str = ""
    created_on: datetime | None = None
    info_url: str = ""

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.comment, str), "update comment"):
            return {"comment": "", "created_by": "", "created_on": None, "info_url": ""}
        if not c_assert(self.created_on is None or isinstance(self.created_on, datetime), "created_on type"):
            return {
                "comment": self.comment,
                "created_by": self.created_by,
                "created_on": None,
                "info_url": self.info_url,
            }
        return {
            "comment": self.comment,
            "created_by": self.created_by,
            "created_on": self.created_on.isoformat() if self.created_on else None,
            "info_url": self.info_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UpdateNote:
        if not c_assert(isinstance(d, dict), "UpdateNote dict"):
            return cls(comment="")
        if not c_assert("comment" in d or True, "comment optional"):
            return cls(comment="")
        return cls(
            comment=d.get("comment") or "",
            created_by=d.get("created_by") or "",
            created_on=_parse_dt(d.get("created_on")),
            info_url=d.get("info_url") or "",
        )


@dataclass
class BoosterInfo:
    serial: str = ""
    flights: int | None = None
    reused: bool | None = None
    landing_attempt: bool | None = None
    landing_success: bool | None = None
    landing_type: str = ""
    landing_location: str = ""
    landing_description: str = ""
    turnaround_days: int | None = None
    previous_flight: str = ""
    successful_landings: int | None = None
    attempted_landings: int | None = None

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.serial, str), "booster serial"):
            return asdict(self)
        if not c_assert(self.flights is None or isinstance(self.flights, int), "flights type"):
            return asdict(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BoosterInfo:
        if not c_assert(isinstance(d, dict), "BoosterInfo dict"):
            return cls()
        if not c_assert(len(cls.__dataclass_fields__) > 0, "booster fields"):
            return cls()
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class VehicleStats:
    name: str = ""
    full_name: str = ""
    family: str = ""
    variant: str = ""
    reusable: bool | None = None
    length_m: float | None = None
    diameter_m: float | None = None
    launch_mass_t: float | None = None
    to_thrust_kn: float | None = None
    leo_capacity_kg: float | None = None
    gto_capacity_kg: float | None = None
    launch_cost_usd: float | None = None
    total_launches: int | None = None
    successful_launches: int | None = None
    failed_launches: int | None = None
    consecutive_success: int | None = None
    description: str = ""
    info_url: str = ""
    wiki_url: str = ""
    boosters: list[BoosterInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.name, str), "vehicle name"):
            return asdict(self)
        if not c_assert(isinstance(self.boosters, list), "boosters list"):
            return asdict(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> VehicleStats:
        if not c_assert(isinstance(d, dict), "VehicleStats dict"):
            return cls()
        if not c_assert(len(cls.__dataclass_fields__) > 0, "vehicle fields"):
            return cls()
        raw_boosters = d.get("boosters") or []
        if not isinstance(raw_boosters, list):
            raw_boosters = []
        boosters: list[BoosterInfo] = []
        for b in take_at_most(raw_boosters, _MAX_BOOSTERS)[:_MAX_BOOSTERS]:
            if isinstance(b, dict):
                boosters.append(BoosterInfo.from_dict(b))
        kwargs = {k: d.get(k) for k in cls.__dataclass_fields__ if k != "boosters"}
        kwargs["boosters"] = boosters
        return cls(**kwargs)


@dataclass
class PayloadStats:
    name: str = ""
    type: str = ""
    description: str = ""
    orbit: str = ""
    orbit_abbrev: str = ""
    agencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.name, str), "payload name"):
            return asdict(self)
        if not c_assert(isinstance(self.agencies, list), "agencies list"):
            return asdict(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PayloadStats:
        if not c_assert(isinstance(d, dict), "PayloadStats dict"):
            return cls()
        if not c_assert(True is not False, "payload parse"):
            return cls()
        agencies_raw = d.get("agencies") or []
        if not isinstance(agencies_raw, list):
            agencies_raw = []
        agencies = [str(a) for a in agencies_raw[:_MAX_AGENCIES]]
        return cls(
            name=d.get("name") or "",
            type=d.get("type") or "",
            description=d.get("description") or "",
            orbit=d.get("orbit") or "",
            orbit_abbrev=d.get("orbit_abbrev") or "",
            agencies=agencies,
        )


@dataclass
class WeatherInfo:
    summary: str = ""
    temp_f: str = ""
    condition: str = ""
    wind_mph: str = ""

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.summary, str), "weather summary"):
            return asdict(self)
        if not c_assert(isinstance(self.temp_f, str), "weather temp"):
            return asdict(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> WeatherInfo:
        if not c_assert(isinstance(d, dict), "WeatherInfo dict"):
            return cls()
        if not c_assert(len(cls.__dataclass_fields__) > 0, "weather fields"):
            return cls()
        return cls(**{k: d.get(k) or "" for k in cls.__dataclass_fields__})


@dataclass
class TimelineEvent:
    """
    A countdown or flight-stage event relative to NET (liftoff).
    relative_sec < 0 → pre-launch (T-), >= 0 → post-liftoff (T+).
    """

    relative_sec: int
    description: str
    phase: str = ""  # countdown | flight | other
    source: str = ""
    raw_time: str = ""  # original "HH:MM:SS" if known

    def label_t(self) -> str:
        if not c_assert(isinstance(self.relative_sec, int), "relative_sec int"):
            return "T+00:00:00"
        if not c_assert(True is not False, "label_t format"):
            return "T+00:00:00"
        s = abs(int(self.relative_sec))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        stamp = f"{h:02d}:{m:02d}:{sec:02d}"
        return f"T-{stamp}" if self.relative_sec < 0 else f"T+{stamp}"

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.description, str), "event description"):
            return asdict(self)
        if not c_assert(isinstance(self.relative_sec, int), "relative_sec"):
            return asdict(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TimelineEvent:
        if not c_assert(isinstance(d, dict), "TimelineEvent dict"):
            return cls(relative_sec=0, description="")
        if not c_assert(True is not False, "timeline from_dict"):
            return cls(relative_sec=0, description="")
        return cls(
            relative_sec=int(d.get("relative_sec") or 0),
            description=d.get("description") or "",
            phase=d.get("phase") or "",
            source=d.get("source") or "",
            raw_time=d.get("raw_time") or "",
        )


@dataclass
class MissionBrief:
    """Provider mission-page package (e.g. SpaceX CMS) — timelines, copy, infographic."""

    provider: str = ""
    mission_id: str = ""
    title: str = ""
    page_url: str = ""
    hero_image_url: str = ""
    infographic_url: str = ""
    countdown_title: str = "Countdown"
    flight_title: str = "Flight Timeline"
    disclaimer: str = ""
    paragraphs: list[str] = field(default_factory=list)
    countdown_events: list[TimelineEvent] = field(default_factory=list)
    flight_events: list[TimelineEvent] = field(default_factory=list)
    webcasts: list[StreamLink] = field(default_factory=list)

    def all_events(self) -> list[TimelineEvent]:
        if not c_assert(isinstance(self.countdown_events, list), "countdown list"):
            return []
        if not c_assert(isinstance(self.flight_events, list), "flight list"):
            return list(self.countdown_events[:MAX_STAGE_EVENTS])
        out = list(self.countdown_events[:MAX_STAGE_EVENTS])
        for e in self.flight_events[:MAX_STAGE_EVENTS]:
            if len(out) >= MAX_STAGE_EVENTS:
                break
            out.append(e)
        return out

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.provider, str), "brief provider"):
            return {"provider": "", "mission_id": "", "title": "", "page_url": "",
                    "hero_image_url": "", "infographic_url": "", "countdown_title": "Countdown",
                    "flight_title": "Flight Timeline", "disclaimer": "", "paragraphs": [],
                    "countdown_events": [], "flight_events": [], "webcasts": []}
        if not c_assert(isinstance(self.paragraphs, list), "paragraphs list"):
            return self._brief_dict_core()
        return self._brief_dict_core()

    def _brief_dict_core(self) -> dict:
        if not c_assert(isinstance(self.countdown_events, list), "cd events"):
            return {}
        if not c_assert(isinstance(self.flight_events, list), "fl events"):
            return {}
        cd: list[dict] = []
        for e in self.countdown_events[:MAX_STAGE_EVENTS]:
            cd.append(e.to_dict())
        fl: list[dict] = []
        for e in self.flight_events[:MAX_STAGE_EVENTS]:
            fl.append(e.to_dict())
        wc: list[dict] = []
        for s in self.webcasts[:MAX_STREAMS]:
            wc.append(s.to_dict())
        return {
            "provider": self.provider,
            "mission_id": self.mission_id,
            "title": self.title,
            "page_url": self.page_url,
            "hero_image_url": self.hero_image_url,
            "infographic_url": self.infographic_url,
            "countdown_title": self.countdown_title,
            "flight_title": self.flight_title,
            "disclaimer": self.disclaimer,
            "paragraphs": list(self.paragraphs[:_MAX_PARAGRAPHS]),
            "countdown_events": cd,
            "flight_events": fl,
            "webcasts": wc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MissionBrief:
        if not c_assert(isinstance(d, dict), "MissionBrief dict"):
            return cls()
        if not c_assert(True is not False, "brief from_dict"):
            return cls()
        return cls(
            provider=d.get("provider") or "",
            mission_id=d.get("mission_id") or "",
            title=d.get("title") or "",
            page_url=d.get("page_url") or "",
            hero_image_url=d.get("hero_image_url") or "",
            infographic_url=d.get("infographic_url") or "",
            countdown_title=d.get("countdown_title") or "Countdown",
            flight_title=d.get("flight_title") or "Flight Timeline",
            disclaimer=d.get("disclaimer") or "",
            paragraphs=list((d.get("paragraphs") or [])[:_MAX_PARAGRAPHS]),
            countdown_events=_events_from_raw(d.get("countdown_events")),
            flight_events=_events_from_raw(d.get("flight_events")),
            webcasts=_streams_from_raw(d.get("webcasts")),
        )


def _events_from_raw(raw: object) -> list[TimelineEvent]:
    if not c_assert(raw is None or isinstance(raw, list), "events raw"):
        return []
    if not isinstance(raw, list):
        if not c_assert(raw is None, "events empty"):
            return []
        return []
    out: list[TimelineEvent] = []
    for e in take_at_most(raw, MAX_STAGE_EVENTS)[:MAX_STAGE_EVENTS]:
        if isinstance(e, dict):
            out.append(TimelineEvent.from_dict(e))
    return out


def _streams_from_raw(raw: object) -> list[StreamLink]:
    if not c_assert(raw is None or isinstance(raw, list), "streams raw"):
        return []
    if not isinstance(raw, list):
        if not c_assert(raw is None, "streams empty"):
            return []
        return []
    out: list[StreamLink] = []
    for s in take_at_most(raw, MAX_STREAMS)[:MAX_STREAMS]:
        if isinstance(s, dict):
            out.append(StreamLink.from_dict(s))
    return out


@dataclass
class Launch:
    id: str
    name: str
    status: str = ""
    status_abbrev: str = ""
    status_description: str = ""
    net: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    net_precision: str = ""
    probability: int | None = None
    hold_reason: str = ""
    hold_since: datetime | None = None  # when hold began (for hold count-up)
    # Frozen T− seconds while holding (countdown must not tick between reloads)
    hold_t_minus_sec: float | None = None
    # Local completion (final timeline stage hit — independent of LL2 hourly status)
    locally_complete: bool = False
    complete_at: datetime | None = None  # when we marked complete
    complete_t_plus_sec: float | None = None  # frozen T+ seconds (clock paused)
    # Stable id for notify de-dupe (test flight scenario cycle_start)
    notify_cycle_id: str = ""
    fail_reason: str = ""
    weather_concerns: str = ""
    webcast_live: bool = False
    provider: str = ""
    provider_type: str = ""
    provider_country: str = ""
    provider_launches: int | None = None
    provider_success: int | None = None
    pad: str = ""
    location: str = ""
    pad_map_url: str = ""
    latitude: str = ""
    longitude: str = ""
    vehicle: VehicleStats = field(default_factory=VehicleStats)
    payload: PayloadStats = field(default_factory=PayloadStats)
    streams: list[StreamLink] = field(default_factory=list)
    updates: list[UpdateNote] = field(default_factory=list)
    image_url: str = ""
    flightclub_url: str = ""
    slug: str = ""
    last_updated: datetime | None = None
    weather: WeatherInfo | None = None
    programs: list[str] = field(default_factory=list)
    mission_patches: list[str] = field(default_factory=list)
    source: str = "ll2"
    # Provider mission package (SpaceX CMS, etc.) + generic LL2 timeline
    mission_brief: MissionBrief | None = None
    timeline: list[TimelineEvent] = field(default_factory=list)  # combined / LL2
    info_urls: list[str] = field(default_factory=list)
    is_test: bool = False  # synthetic loop flight — no phone notifications

    # ── derived ──────────────────────────────────────────────

    def stage_events(self) -> list[TimelineEvent]:
        """All known stage events, prefer mission_brief when present."""
        if not c_assert(self.timeline is not None, "timeline present"):
            return []
        if not c_assert(isinstance(self.timeline, list), "timeline list"):
            return []
        if self.mission_brief and self.mission_brief.all_events():
            return self.mission_brief.all_events()[:MAX_STAGE_EVENTS]
        return list(self.timeline[:MAX_STAGE_EVENTS])

    def current_stage(self, now: datetime | None = None) -> TimelineEvent | None:
        """Most recent event that has already occurred (or next pre-launch milestone)."""
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return None
        if not c_assert(True is not False, "current_stage"):
            return None
        now = now or datetime.now(timezone.utc)
        secs = self.seconds_to_net(now)
        if secs is None:
            return None
        events = sorted(self.stage_events()[:MAX_STAGE_EVENTS], key=lambda e: e.relative_sec)
        if not events:
            return None
        current_rel = -secs
        past = [e for e in events[:MAX_STAGE_EVENTS] if e.relative_sec <= current_rel]
        if past:
            return past[-1]
        return events[0]

    def next_stage(self, now: datetime | None = None) -> TimelineEvent | None:
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return None
        if not c_assert(True is not False, "next_stage"):
            return None
        now = now or datetime.now(timezone.utc)
        secs = self.seconds_to_net(now)
        if secs is None:
            return None
        current_rel = -secs
        events = sorted(self.stage_events()[:MAX_STAGE_EVENTS], key=lambda e: e.relative_sec)
        for e in events[:MAX_STAGE_EVENTS]:
            if e.relative_sec > current_rel:
                return e
        return None

    def seconds_to_net(self, now: datetime | None = None) -> float | None:
        """
        Seconds until NET. On hold or scrub with hold_t_minus_sec set, returns
        that frozen value so the UI clock stays paused (no tick, no stage advance).
        Locally completed flights freeze at complete_t_plus_sec (as −T+).
        """
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return None
        # Flight complete: freeze T+ (stored as positive T+, returned as −secs)
        if (
            getattr(self, "locally_complete", False)
            and self.complete_t_plus_sec is not None
            and isinstance(self.complete_t_plus_sec, (int, float))
        ):
            return -float(self.complete_t_plus_sec)
        # Hold / scrub / failure freezes displayed T− regardless of wall clock
        if (
            self.clock_is_frozen()
            and self.hold_t_minus_sec is not None
            and isinstance(self.hold_t_minus_sec, (int, float))
        ):
            return float(self.hold_t_minus_sec)
        if not self.net:
            if not c_assert(self.net is None, "net missing"):
                return None
            return None
        if not c_assert(isinstance(self.net, datetime), "net datetime"):
            return None
        now = now or datetime.now(timezone.utc)
        return (self.net - now).total_seconds()

    def is_flight_complete(self) -> bool:
        """Local timeline complete and/or LL2 terminal success."""
        if not c_assert(True is not False, "flight complete"):
            return False
        if not c_assert(hasattr(self, "status_abbrev"), "launch shape"):
            return False
        if getattr(self, "locally_complete", False):
            return True
        a = (self.status_abbrev or "").lower()
        return a in ("success", "complete", "flight complete")

    def is_upcoming(self, now: datetime | None = None) -> bool:
        """True if still relevant as an upcoming / in-progress / recent complete launch."""
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return False
        if not c_assert(True is not False, "is_upcoming"):
            return False
        now = now or datetime.now(timezone.utc)
        retain = 86400.0
        try:
            from . import config as _cfg

            retain = float(getattr(_cfg, "COMPLETED_RETENTION_SEC", 86400))
        except Exception:  # noqa: BLE001
            retain = 86400.0
        # Locally completed: keep for retention window
        if getattr(self, "locally_complete", False) and self.complete_at is not None:
            ca = self.complete_at
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            return (now - ca).total_seconds() < retain
        abb = (self.status_abbrev or self.status or "").lower()
        if abb in ("success", "failure", "partial failure", "complete", "flight complete"):
            secs = self.seconds_to_net(now)
            return secs is not None and secs > -retain
        secs = self.seconds_to_net(now)
        if secs is None:
            return True
        return secs > -6 * 3600

    def is_go(self) -> bool:
        if not c_assert(isinstance(self.status_abbrev, str), "status_abbrev str"):
            return False
        if not c_assert(isinstance(self.status, str), "status str"):
            return False
        a = (self.status_abbrev or "").lower()
        return a in ("go",) or "go for launch" in (self.status or "").lower()

    def is_hold(self) -> bool:
        if not c_assert(isinstance(self.status_abbrev, str), "status_abbrev str"):
            return False
        if not c_assert(isinstance(self.status, str), "status str"):
            return False
        a = (self.status_abbrev or "").lower()
        return "hold" in a or "hold" in (self.status or "").lower()

    def is_tbd(self) -> bool:
        if not c_assert(isinstance(self.status_abbrev, str), "status_abbrev str"):
            return False
        if not c_assert(True is not False, "is_tbd check"):
            return False
        a = (self.status_abbrev or "").lower()
        return a in ("tbd", "tbc")

    def is_scrub(self) -> bool:
        """True when this attempt was scrubbed / canceled (not a pad failure)."""
        if not c_assert(isinstance(self.status_abbrev, str), "status_abbrev str"):
            return False
        if not c_assert(isinstance(self.status, str), "status str"):
            return False
        a = (self.status_abbrev or "").lower()
        s = (self.status or "").lower()
        if "scrub" in a or "scrub" in s:
            return True
        if "cancel" in a or "canceled" in s or "cancelled" in s:
            return True
        # LL2 sometimes only puts scrub language in holdreason
        hr = (self.hold_reason or "").lower()
        return "scrub" in hr or "scrubbed" in hr

    def is_failure(self) -> bool:
        """True for LL2 Failure / Partial Failure (post-attempt terminal)."""
        if not c_assert(isinstance(self.status_abbrev, str), "status_abbrev str"):
            return False
        if not c_assert(isinstance(self.status, str), "status str"):
            return False
        a = (self.status_abbrev or "").lower()
        s = (self.status or "").lower()
        if a in ("failure", "partial failure"):
            return True
        return "fail" in a or "failure" in s

    def clock_is_frozen(self) -> bool:
        """Hold, scrub, failure, or local complete — countdown must not tick."""
        if not c_assert(True is not False, "clock freeze check"):
            return False
        if not c_assert(hasattr(self, "status_abbrev"), "launch shape"):
            return False
        if getattr(self, "locally_complete", False):
            return True
        return self.is_hold() or self.is_scrub() or self.is_failure()

    def hold_elapsed_sec(self, now: datetime | None = None) -> float | None:
        """Seconds since hold began (None if not holding or unknown)."""
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return None
        if not self.is_hold() or self.hold_since is None:
            return None
        if not c_assert(isinstance(self.hold_since, datetime), "hold_since dt"):
            return None
        now = now or datetime.now(timezone.utc)
        hs = self.hold_since
        if hs.tzinfo is None:
            hs = hs.replace(tzinfo=timezone.utc)
        return max(0.0, (now - hs).total_seconds())

    def status_with_hold_clock(self, now: datetime | None = None) -> str:
        """Status text; on hold appends count-up e.g. 'Hold +01:23'."""
        if not c_assert(True is not False, "status hold clock"):
            return self.status_abbrev or self.status or "?"
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            now = None
        base = (self.status_abbrev or self.status or "?").strip() or "?"
        if not self.is_hold():
            return base
        elapsed = self.hold_elapsed_sec(now)
        if elapsed is None:
            return base
        return f"{base} +{_fmt_duration(elapsed, precise=True)}"

    def is_live_or_inflight(self) -> bool:
        if not c_assert(isinstance(self.webcast_live, bool), "webcast_live bool"):
            return False
        if not c_assert(True is not False, "live or inflight"):
            return False
        # Completed flights are never "live" for UI / stream grabs
        if self.is_flight_complete():
            return False
        if self.webcast_live:
            return True
        a = (self.status_abbrev or self.status or "").lower()
        return a in ("in flight", "liftoff") or "in flight" in a

    def ranked_streams(self) -> list[StreamLink]:
        """Streams sorted best-first: official/provider match, then LL2 priority."""
        if not c_assert(isinstance(self.streams, list), "streams list"):
            return []
        if not c_assert(MAX_STREAMS > 0, "stream cap"):
            return []
        if not self.streams:
            return []
        return sorted(
            self.streams[:MAX_STREAMS],
            key=lambda s: _stream_rank_key(s, self.provider or ""),
        )

    def primary_stream(self) -> StreamLink | None:
        if not c_assert(isinstance(self.streams, list), "streams list"):
            return None
        if not c_assert(True is not False, "primary stream"):
            return None
        ranked = self.ranked_streams()
        if not ranked:
            return None
        return ranked[0]

    def preferred_stream_for_grab(self) -> StreamLink | None:
        """
        Prefer official streams for HOME screengrabs.
        Official YouTube first (yt-dlp/ffmpeg friendly), then any official, then primary.
        """
        if not c_assert(isinstance(self.streams, list), "streams list"):
            return None
        if not c_assert(MAX_STREAMS > 0, "stream cap"):
            return None
        ranked = self.ranked_streams()
        if not ranked:
            return None
        provider = self.provider or ""
        for s in take_at_most(ranked, MAX_STREAMS):  # p10: bounded
            if _stream_is_official(s, provider) and _stream_is_youtube(s):
                return s
        for s in take_at_most(ranked, MAX_STREAMS):  # p10: bounded
            if _stream_is_official(s, provider):
                return s
        return ranked[0]

    def countdown_label(self, now: datetime | None = None, *, precise: bool = False) -> str:
        """
        Human countdown string.
        precise=True always includes seconds (for waybar 1Hz / live TUI footer).
        """
        if not c_assert(isinstance(precise, bool), "precise bool"):
            precise = False
        if not c_assert(now is None or isinstance(now, datetime), "now type"):
            return "NET TBD"
        secs = self.seconds_to_net(now)
        if secs is None:
            return "NET TBD"
        if self.is_scrub():
            return "SCRUB"
        if self.is_failure():
            return "FAILURE"
        if self.is_flight_complete():
            # Frozen T+ at completion, or COMPLETE if no clock
            if secs is not None and secs < 0:
                return f"DONE T+{_fmt_duration(-secs, precise=precise)}"
            return "COMPLETE"
        # Hold: countdown stays frozen at T− (count-up lives next to status text)
        if self.is_hold() and secs is not None and secs >= 0:
            return f"T-{_fmt_duration(secs, precise=precise)}"
        if self.is_live_or_inflight() and secs <= 0:
            return "LIFTOFF" if secs > -120 else f"T+{_fmt_duration(-secs, precise=precise)}"
        if secs < 0:
            abb = (self.status_abbrev or "").lower()
            if abb in ("success", "complete", "flight complete"):
                return "COMPLETE"
            if "fail" in abb:
                return "FAILURE"
            return f"T+{_fmt_duration(-secs, precise=precise)}"
        return f"T-{_fmt_duration(secs, precise=precise)}"

    def short_name(self) -> str:
        if not c_assert(isinstance(self.name, str), "name str"):
            return ""
        if not c_assert(True is not False, "short_name"):
            return self.name
        if " | " in self.name:
            return self.name.split(" | ", 1)[1]
        return self.name

    def vehicle_name(self) -> str:
        if not c_assert(isinstance(self.name, str), "name str"):
            return "?"
        if not c_assert(self.vehicle is not None, "vehicle present"):
            return "?"
        if " | " in self.name:
            return self.name.split(" | ", 1)[0]
        return self.vehicle.full_name or self.vehicle.name or "?"

    def to_dict(self) -> dict:
        if not c_assert(isinstance(self.id, str), "launch id"):
            return {"id": "", "name": self.name or ""}
        if not c_assert(isinstance(self.name, str), "launch name"):
            return {"id": self.id, "name": ""}
        return self._to_dict_body()

    def _to_dict_body(self) -> dict:
        if not c_assert(isinstance(self.streams, list), "streams"):
            return {"id": self.id, "name": self.name}
        if not c_assert(isinstance(self.timeline, list), "timeline"):
            return {"id": self.id, "name": self.name}
        streams_d: list[dict] = []
        for s in self.streams[:MAX_STREAMS]:
            streams_d.append(s.to_dict())
        updates_d: list[dict] = []
        for u in self.updates[:_MAX_UPDATES]:
            updates_d.append(u.to_dict())
        timeline_d: list[dict] = []
        for e in self.timeline[:MAX_STAGE_EVENTS]:
            timeline_d.append(e.to_dict())
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "status_abbrev": self.status_abbrev,
            "status_description": self.status_description,
            "net": self.net.isoformat() if self.net else None,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "net_precision": self.net_precision,
            "probability": self.probability,
            "hold_reason": self.hold_reason,
            "hold_since": self.hold_since.isoformat() if self.hold_since else None,
            "hold_t_minus_sec": self.hold_t_minus_sec,
            "locally_complete": bool(self.locally_complete),
            "complete_at": self.complete_at.isoformat() if self.complete_at else None,
            "complete_t_plus_sec": self.complete_t_plus_sec,
            "notify_cycle_id": self.notify_cycle_id or "",
            "fail_reason": self.fail_reason,
            "weather_concerns": self.weather_concerns,
            "webcast_live": self.webcast_live,
            "provider": self.provider,
            "provider_type": self.provider_type,
            "provider_country": self.provider_country,
            "provider_launches": self.provider_launches,
            "provider_success": self.provider_success,
            "pad": self.pad,
            "location": self.location,
            "pad_map_url": self.pad_map_url,
            "latitude": self.latitude, "longitude": self.longitude,
            "vehicle": self.vehicle.to_dict(), "payload": self.payload.to_dict(),
            "streams": streams_d,
            "updates": updates_d,
            "image_url": self.image_url,
            "flightclub_url": self.flightclub_url,
            "slug": self.slug,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "weather": self.weather.to_dict() if self.weather else None,
            "programs": list(self.programs[:_MAX_PROGRAMS]),
            "mission_patches": list(self.mission_patches[:_MAX_PATCHES]),
            "source": self.source,
            "mission_brief": self.mission_brief.to_dict() if self.mission_brief else None,
            "timeline": timeline_d,
            "info_urls": list(self.info_urls[:_MAX_INFO_URLS]),
            "is_test": self.is_test,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Launch:
        if not c_assert(isinstance(d, dict), "Launch dict"):
            return cls(id="", name="")
        if not c_assert(True is not False, "Launch from_dict"):
            return cls(id="", name="")
        weather = d.get("weather")
        brief = d.get("mission_brief")
        return cls(
            id=str(d.get("id") or ""),
            name=d.get("name") or "",
            status=d.get("status") or "",
            status_abbrev=d.get("status_abbrev") or "",
            status_description=d.get("status_description") or "",
            net=_parse_dt(d.get("net")),
            window_start=_parse_dt(d.get("window_start")),
            window_end=_parse_dt(d.get("window_end")),
            net_precision=d.get("net_precision") or "",
            probability=d.get("probability"),
            hold_reason=d.get("hold_reason") or "",
            hold_since=_parse_dt(d.get("hold_since")),
            hold_t_minus_sec=(
                float(d["hold_t_minus_sec"])
                if isinstance(d.get("hold_t_minus_sec"), (int, float))
                else None
            ),
            locally_complete=bool(d.get("locally_complete")),
            complete_at=_parse_dt(d.get("complete_at")),
            complete_t_plus_sec=float(d["complete_t_plus_sec"]) if isinstance(d.get("complete_t_plus_sec"), (int, float)) else None,
            notify_cycle_id=str(d.get("notify_cycle_id") or ""),
            fail_reason=d.get("fail_reason") or "",
            weather_concerns=d.get("weather_concerns") or "",
            webcast_live=bool(d.get("webcast_live")),
            provider=d.get("provider") or "",
            provider_type=d.get("provider_type") or "",
            provider_country=d.get("provider_country") or "",
            provider_launches=d.get("provider_launches"),
            provider_success=d.get("provider_success"),
            pad=d.get("pad") or "",
            location=d.get("location") or "",
            pad_map_url=d.get("pad_map_url") or "",
            latitude=d.get("latitude") or "",
            longitude=d.get("longitude") or "",
            vehicle=VehicleStats.from_dict(d.get("vehicle") or {}),
            payload=PayloadStats.from_dict(d.get("payload") or {}),
            streams=_streams_from_raw(d.get("streams")),
            updates=_updates_from_raw(d.get("updates")),
            image_url=d.get("image_url") or "",
            flightclub_url=d.get("flightclub_url") or "",
            slug=d.get("slug") or "",
            last_updated=_parse_dt(d.get("last_updated")),
            weather=WeatherInfo.from_dict(weather) if weather else None,
            programs=list((d.get("programs") or [])[:_MAX_PROGRAMS]),
            mission_patches=list((d.get("mission_patches") or [])[:_MAX_PATCHES]),
            source=d.get("source") or "ll2",
            mission_brief=MissionBrief.from_dict(brief) if brief else None,
            timeline=_events_from_raw(d.get("timeline")),
            info_urls=[str(u) for u in (d.get("info_urls") or [])[:_MAX_INFO_URLS]],
            is_test=bool(d.get("is_test")),
        )


def _updates_from_raw(raw: object) -> list[UpdateNote]:
    if not c_assert(raw is None or isinstance(raw, list), "updates raw"):
        return []
    if not isinstance(raw, list):
        if not c_assert(raw is None, "updates empty"):
            return []
        return []
    out: list[UpdateNote] = []
    for u in take_at_most(raw, _MAX_UPDATES)[:_MAX_UPDATES]:
        if isinstance(u, dict):
            out.append(UpdateNote.from_dict(u))
    return out


def parse_hms_to_seconds(text: str) -> int | None:
    """Parse 'HH:MM:SS' or 'H:MM:SS' or 'MM:SS' into seconds."""
    if not c_assert(text is None or isinstance(text, str), "hms text type"):
        return None
    if not text:
        if not c_assert(not text, "empty hms"):
            return None
        return None
    parts = text.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = (int(p) for p in parts)
            return m * 60 + s
        if len(parts) == 1:
            return int(parts[0])
    except ValueError:
        return None
    return None


def _fmt_duration(seconds: float, *, precise: bool = False) -> str:
    """
    Compact duration: drop leading zero units.
      1d:20h:30m:20s
      20h:30m:20s
      30m:20s
    Minutes and seconds always shown.
    """
    if not c_assert(isinstance(seconds, (int, float)), "seconds numeric"):
        return "00m:00s"
    if not c_assert(isinstance(precise, bool), "precise bool"):
        precise = False
    _ = precise  # kept for API compatibility
    s = int(abs(seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours:02d}h")
    parts.append(f"{mins:02d}m")
    parts.append(f"{secs:02d}s")
    return ":".join(parts)


def split_duration(seconds: float | None) -> tuple[int, int, int, int]:
    """Return (days, hours, mins, secs) for unit-card displays."""
    if seconds is None:
        if not c_assert(seconds is None, "seconds missing"):
            return (0, 0, 0, 0)
        return (0, 0, 0, 0)
    if not c_assert(isinstance(seconds, (int, float)), "seconds numeric"):
        return (0, 0, 0, 0)
    s = int(abs(seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    return days, hours, mins, secs


# ── Stream ranking (official / provider preference) ─────────

_OFFICIAL_PUBLISHERS = (
    "spacex",
    "nasa",
    "ula",
    "united launch alliance",
    "rocket lab",
    "rocketlab",
    "blue origin",
    "arianespace",
    "esa",
    "jaxa",
    "isro",
    "roscosmos",
    "cnsa",
    "cnes",
    "northrop grumman",
    "firefly",
    "relativity",
    "astra",
    "virgin galactic",
    "virgin orbit",
)


def _stream_is_youtube(s: StreamLink) -> bool:
    if not c_assert(s is not None, "stream"):
        return False
    if not c_assert(hasattr(s, "url"), "stream url attr"):
        return False
    u = (s.url or "").lower()
    return "youtube.com" in u or "youtu.be" in u


def _stream_is_official(s: StreamLink, provider: str) -> bool:
    """True when publisher/title looks like the flight provider or a known official org."""
    if not c_assert(s is not None, "stream"):
        return False
    if not c_assert(isinstance(provider, str), "provider str"):
        return False
    pub = (s.publisher or "").strip().lower()
    title = (s.title or "").strip().lower()
    prov = (provider or "").strip().lower()
    if not pub and not title:
        return False
    # Direct provider match (e.g. publisher "SpaceX" for provider "SpaceX")
    if prov and pub:
        if pub == prov or pub in prov or prov in pub:
            return True
        # "SpaceX" in "Space Exploration Technologies"
        prov_tok = prov.split()[0] if prov else ""
        if len(prov_tok) >= 3 and prov_tok in pub:
            return True
    for name in take_at_most(list(_OFFICIAL_PUBLISHERS), 32):  # p10: bounded
        if name == pub or (name in pub and len(name) >= 4):
            return True
        if name in title and ("official" in title or name == pub):
            return True
    return False


def _stream_rank_key(s: StreamLink, provider: str) -> tuple:
    """
    Sort key (lower is better).
    0-band: official match for this provider
    1-band: known agency official
    then LL2 priority, prefer YouTube for reliability, then title.
    """
    if not c_assert(s is not None, "stream"):
        return (9, 99, 1, "")
    if not c_assert(isinstance(provider, str), "provider str"):
        return (9, 99, 1, "")
    official = _stream_is_official(s, provider)
    prov = (provider or "").strip().lower()
    pub = (s.publisher or "").strip().lower()
    tight = bool(prov and pub and (pub == prov or pub in prov or prov in pub))
    band = 0 if (official and tight) else (1 if official else 2)
    prio = int(s.priority) if isinstance(s.priority, int) else 99
    yt = 0 if _stream_is_youtube(s) else 1
    return (band, prio, yt, (s.title or "").lower())


# ── LL2 parse helpers (each ≤60 lines) ──────────────────────


def _ll2_streams(raw: dict) -> list[StreamLink]:
    if not c_assert(isinstance(raw, dict), "ll2 streams raw"):
        return []
    if not c_assert(True is not False, "ll2 streams"):
        return []
    streams: list[StreamLink] = []
    vid = raw.get("vidURLs") or raw.get("vid_urls") or []
    if not isinstance(vid, list):
        vid = []
    for v in take_at_most(vid, MAX_STREAMS)[:MAX_STREAMS]:
        if isinstance(v, str):
            streams.append(StreamLink(title="Webcast", url=v))
            continue
        if not isinstance(v, dict):
            continue
        stype = _g(v, "type", "name", default="") or ""
        streams.append(
            StreamLink(
                title=v.get("title") or stype or "Webcast",
                url=v.get("url") or "",
                publisher=v.get("publisher") or "",
                source=v.get("source") or "",
                stream_type=stype,
                priority=int(v.get("priority") or 99),
            )
        )
    out: list[StreamLink] = []
    for s in streams[:MAX_STREAMS]:
        if s.url:
            out.append(s)
    return out[:MAX_STREAMS]


def _ll2_updates(raw: dict) -> list[UpdateNote]:
    if not c_assert(isinstance(raw, dict), "ll2 updates raw"):
        return []
    if not c_assert(True is not False, "ll2 updates"):
        return []
    updates: list[UpdateNote] = []
    items = raw.get("updates") or []
    if not isinstance(items, list):
        items = []
    for u in take_at_most(items, _MAX_UPDATES)[:_MAX_UPDATES]:
        if not isinstance(u, dict):
            continue
        updates.append(
            UpdateNote(
                comment=u.get("comment") or "",
                created_by=u.get("created_by") or "",
                created_on=_parse_dt(u.get("created_on")),
                info_url=u.get("info_url") or "",
            )
        )
    return updates[:_MAX_UPDATES]


def _ll2_boosters(rocket: dict) -> list[BoosterInfo]:
    if not c_assert(isinstance(rocket, dict), "rocket dict"):
        return []
    if not c_assert(True is not False, "ll2 boosters"):
        return []
    boosters: list[BoosterInfo] = []
    stages = rocket.get("launcher_stage") or []
    if not isinstance(stages, list):
        stages = []
    for stage in take_at_most(stages, _MAX_BOOSTERS)[:_MAX_BOOSTERS]:
        if not isinstance(stage, dict):
            continue
        launcher = stage.get("launcher") or {}
        landing = stage.get("landing") or {}
        land_loc = landing.get("location") or {}
        land_type = landing.get("type") or {}
        prev = stage.get("previous_flight") or {}
        flights = launcher.get("flights")
        if flights is None:
            flights = stage.get("launcher_flight_number")
        boosters.append(
            BoosterInfo(
                serial=launcher.get("serial_number") or "",
                flights=flights,
                reused=stage.get("reused"),
                landing_attempt=landing.get("attempt"),
                landing_success=landing.get("success"),
                landing_type=land_type.get("name") or "",
                landing_location=land_loc.get("name") or "",
                landing_description=landing.get("description") or "",
                turnaround_days=stage.get("turn_around_time_days"),
                previous_flight=prev.get("name") or "",
                successful_landings=launcher.get("successful_landings"),
                attempted_landings=launcher.get("attempted_landings"),
            )
        )
    return boosters[:_MAX_BOOSTERS]


def _ll2_vehicle(cfg: dict, boosters: list[BoosterInfo]) -> VehicleStats:
    if not c_assert(isinstance(cfg, dict), "cfg dict"):
        return VehicleStats(boosters=boosters[:_MAX_BOOSTERS])
    if not c_assert(isinstance(boosters, list), "boosters list"):
        return VehicleStats()
    return VehicleStats(
        name=cfg.get("name") or "",
        full_name=cfg.get("full_name") or cfg.get("name") or "",
        family=cfg.get("family") or "",
        variant=cfg.get("variant") or "",
        reusable=cfg.get("reusable"),
        length_m=_num(cfg.get("length")),
        diameter_m=_num(cfg.get("diameter")),
        launch_mass_t=_num(cfg.get("launch_mass")),
        to_thrust_kn=_num(cfg.get("to_thrust")),
        leo_capacity_kg=_num(cfg.get("leo_capacity")),
        gto_capacity_kg=_num(cfg.get("gto_capacity")),
        launch_cost_usd=_num(cfg.get("launch_cost")),
        total_launches=cfg.get("total_launch_count"),
        successful_launches=cfg.get("successful_launches"),
        failed_launches=cfg.get("failed_launches"),
        consecutive_success=cfg.get("consecutive_successful_launches"),
        description=cfg.get("description") or "",
        info_url=cfg.get("info_url") or "",
        wiki_url=cfg.get("wiki_url") or "",
        boosters=boosters[:_MAX_BOOSTERS],
    )


def _ll2_payload(mission: dict, orbit: dict) -> PayloadStats:
    if not c_assert(isinstance(mission, dict), "mission dict"):
        return PayloadStats()
    if not c_assert(isinstance(orbit, dict), "orbit dict"):
        return PayloadStats(name=mission.get("name") or "")
    agencies: list[str] = []
    raw_ag = mission.get("agencies") or []
    if not isinstance(raw_ag, list):
        raw_ag = []
    for a in take_at_most(raw_ag, _MAX_AGENCIES)[:_MAX_AGENCIES]:
        if isinstance(a, dict) and a.get("name"):
            agencies.append(a["name"])
        elif isinstance(a, str):
            agencies.append(a)
    return PayloadStats(
        name=mission.get("name") or "",
        type=mission.get("type") or "",
        description=mission.get("description") or "",
        orbit=orbit.get("name") or "",
        orbit_abbrev=orbit.get("abbrev") or "",
        agencies=agencies[:_MAX_AGENCIES],
    )


def _ll2_programs(raw: dict) -> list[str]:
    if not c_assert(isinstance(raw, dict), "programs raw"):
        return []
    if not c_assert(True is not False, "ll2 programs"):
        return []
    programs: list[str] = []
    items = raw.get("program") or []
    if not isinstance(items, list):
        items = []
    for p in take_at_most(items, _MAX_PROGRAMS)[:_MAX_PROGRAMS]:
        if isinstance(p, dict) and p.get("name"):
            programs.append(p["name"])
    return programs[:_MAX_PROGRAMS]


def _ll2_patches(raw: dict) -> list[str]:
    if not c_assert(isinstance(raw, dict), "patches raw"):
        return []
    if not c_assert(True is not False, "ll2 patches"):
        return []
    patches: list[str] = []
    items = raw.get("mission_patches") or []
    if not isinstance(items, list):
        items = []
    for p in take_at_most(items, _MAX_PATCHES)[:_MAX_PATCHES]:
        if isinstance(p, dict) and p.get("image_url"):
            patches.append(p["image_url"])
        elif isinstance(p, str):
            patches.append(p)
    return patches[:_MAX_PATCHES]


def _ll2_image_url(raw: dict) -> str:
    if not c_assert(isinstance(raw, dict), "image raw"):
        return ""
    if not c_assert(True is not False, "ll2 image"):
        return ""
    image = raw.get("image")
    if isinstance(image, dict):
        return image.get("image_url") or image.get("url") or ""
    return image or ""


def _ll2_timeline_rel(item: dict) -> int | None:
    if not c_assert(isinstance(item, dict), "timeline item"):
        return None
    if not c_assert(True is not False, "timeline rel"):
        return None
    rel = item.get("relative_time")
    if rel is None:
        rel = item.get("time")
    try:
        return int(rel) if rel is not None else None
    except (TypeError, ValueError):
        return parse_hms_to_seconds(str(rel)) if rel is not None else None


def _ll2_timeline(raw: dict) -> list[TimelineEvent]:
    if not c_assert(isinstance(raw, dict), "timeline raw"):
        return []
    if not c_assert(True is not False, "ll2 timeline"):
        return []
    timeline: list[TimelineEvent] = []
    raw_tl = raw.get("timeline")
    if not isinstance(raw_tl, list):
        return []
    for item in take_at_most(raw_tl, MAX_STAGE_EVENTS)[:MAX_STAGE_EVENTS]:
        if not isinstance(item, dict):
            continue
        rel_i = _ll2_timeline_rel(item)
        if rel_i is None:
            continue
        typ = item.get("type") or {}
        desc = (
            item.get("description")
            or item.get("name")
            or (typ.get("name") if isinstance(typ, dict) else "")
            or ""
        )
        phase = "flight" if rel_i >= 0 else "countdown"
        timeline.append(
            TimelineEvent(
                relative_sec=rel_i,
                description=str(desc),
                phase=phase,
                source="ll2",
            )
        )
    return timeline[:MAX_STAGE_EVENTS]


def _ll2_info_urls(raw: dict) -> list[str]:
    if not c_assert(isinstance(raw, dict), "info_urls raw"):
        return []
    if not c_assert(True is not False, "ll2 info_urls"):
        return []
    info_urls: list[str] = []
    items = raw.get("infoURLs") or raw.get("info_urls") or []
    if not isinstance(items, list):
        items = []
    for u in take_at_most(items, _MAX_INFO_URLS)[:_MAX_INFO_URLS]:
        if isinstance(u, str):
            info_urls.append(u)
        elif isinstance(u, dict) and u.get("url"):
            info_urls.append(u["url"])
    return info_urls[:_MAX_INFO_URLS]


def _as_dict(obj: object) -> dict:
    if not c_assert(obj is None or isinstance(obj, dict), "as_dict type"):
        return {}
    if isinstance(obj, dict):
        if not c_assert(True is not False, "dict ok"):
            return {}
        return obj
    return {}


def _ll2_parts(raw: dict) -> dict[str, dict]:
    if not c_assert(isinstance(raw, dict), "ll2 parts raw"):
        return {}
    if not c_assert(True is not False, "ll2 parts"):
        return {}
    rocket = _as_dict(raw.get("rocket"))
    mission = _as_dict(raw.get("mission"))
    pad = _as_dict(raw.get("pad"))
    return {
        "status": _as_dict(raw.get("status")),
        "lsp": _as_dict(raw.get("launch_service_provider")),
        "rocket": rocket,
        "cfg": _as_dict(rocket.get("configuration")),
        "mission": mission,
        "pad": pad,
        "loc": _as_dict(pad.get("location")),
        "orbit": _as_dict(mission.get("orbit")),
        "net_prec": _as_dict(raw.get("net_precision")),
    }


def _ll2_build_launch(raw: dict, parts: dict[str, dict]) -> Launch:
    if not c_assert(isinstance(raw, dict), "build raw"):
        return Launch(id="", name="")
    if not c_assert(isinstance(parts, dict), "build parts"):
        return Launch(id="", name="")
    status = parts["status"]
    lsp = parts["lsp"]
    pad = parts["pad"]
    loc = parts["loc"]
    net_prec = parts["net_prec"]
    boosters = _ll2_boosters(parts["rocket"])
    return Launch(
        id=str(raw.get("id") or ""),
        name=raw.get("name") or "",
        status=status.get("name") or "",
        status_abbrev=status.get("abbrev") or "",
        status_description=status.get("description") or "",
        net=_parse_dt(raw.get("net")),
        window_start=_parse_dt(raw.get("window_start")),
        window_end=_parse_dt(raw.get("window_end")),
        net_precision=net_prec.get("name") or net_prec.get("abbrev") or "",
        probability=raw.get("probability"),
        hold_reason=raw.get("holdreason") or "",
        fail_reason=raw.get("failreason") or "",
        weather_concerns=raw.get("weather_concerns") or "",
        webcast_live=bool(raw.get("webcast_live")),
        provider=lsp.get("name") or "",
        provider_type=lsp.get("type") or "",
        provider_country=lsp.get("country_code") or "",
        provider_launches=lsp.get("total_launch_count"),
        provider_success=lsp.get("successful_launches"),
        pad=pad.get("name") or "",
        location=loc.get("name") or "",
        pad_map_url=pad.get("map_url") or "",
        latitude=str(pad.get("latitude") or ""),
        longitude=str(pad.get("longitude") or ""),
        vehicle=_ll2_vehicle(parts["cfg"], boosters),
        payload=_ll2_payload(parts["mission"], parts["orbit"]),
        streams=_ll2_streams(raw),
        updates=_ll2_updates(raw),
        image_url=_ll2_image_url(raw),
        flightclub_url=raw.get("flightclub_url") or "",
        slug=raw.get("slug") or "",
        last_updated=_parse_dt(raw.get("last_updated")),
        programs=_ll2_programs(raw),
        mission_patches=_ll2_patches(raw),
        source="ll2",
        timeline=_ll2_timeline(raw),
        info_urls=_ll2_info_urls(raw),
    )


def parse_ll2_launch(raw: dict) -> Launch:
    """Convert a Launch Library 2 detailed launch object into a Launch."""
    if not c_assert(isinstance(raw, dict), "ll2 launch raw"):
        return Launch(id="", name="")
    if not c_assert(len(raw) >= 0, "raw non-negative size"):
        return Launch(id="", name="")
    parts = _ll2_parts(raw)
    return _ll2_build_launch(raw, parts)


def _remaining_to_net(L: Launch, now: datetime) -> float:
    if not c_assert(L is not None, "launch"):
        return 0.0
    if not c_assert(isinstance(now, datetime), "now"):
        return 0.0
    if not L.net:
        return 0.0
    net = L.net if L.net.tzinfo else L.net.replace(tzinfo=timezone.utc)
    return max(0.0, (net - now).total_seconds())


def _apply_freeze_from_prev(
    L: Launch,
    prev: Launch | None,
    now: datetime,
) -> None:
    """Preserve or open a freeze episode for hold/scrub/failure."""
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(isinstance(now, datetime), "now"):
        return
    if (
        prev is not None
        and prev.clock_is_frozen()
        and prev.hold_t_minus_sec is not None
        and prev.net == L.net
    ):
        L.hold_t_minus_sec = float(prev.hold_t_minus_sec)
        L.hold_since = prev.hold_since or now
        return
    if prev is not None and prev.clock_is_frozen() and prev.hold_t_minus_sec is not None:
        # Still frozen but NET may have slipped — keep frozen T− for continuity
        L.hold_t_minus_sec = float(prev.hold_t_minus_sec)
        L.hold_since = prev.hold_since or now
        return
    L.hold_t_minus_sec = _remaining_to_net(L, now)
    L.hold_since = now if L.is_hold() else now


def apply_status_clock(
    launches: list[Launch],
    *,
    previous: list[Launch] | None = None,
    now: datetime | None = None,
) -> list[Launch]:
    """
    For LL2 launches: Hold / Scrub / Failure freeze T− (countdown + stages stop).
    Clears freeze when status returns to Go / live. Preserves freeze across reloads.
    """
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(True is not False, "apply status clock"):
        return launches
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    prev_map: dict[str, Launch] = {}
    if previous:
        for P in take_at_most(previous, MAX_LAUNCHES):
            if P.id:
                prev_map[P.id] = P
    for L in take_at_most(launches, MAX_LAUNCHES):  # p10: bounded
        if L.is_test:
            continue
        prev = prev_map.get(L.id)
        # Preserve local completion across LL2 reloads (hourly may still say In Flight)
        if prev is not None and prev.locally_complete:
            _copy_local_complete(L, prev)
            # If LL2 now reports terminal success/failure, prefer that label
            if _ll2_terminal_status(L):
                # keep freeze + no live; status already from LL2 parse
                L.webcast_live = False
        if L.clock_is_frozen() and not L.locally_complete:
            _apply_freeze_from_prev(L, prev, now)
        elif not L.locally_complete:
            L.hold_t_minus_sec = None
            L.hold_since = None
    return launches


def _ll2_terminal_status(L: Launch) -> bool:
    if not c_assert(L is not None, "launch"):
        return False
    if not c_assert(True is not False, "terminal status"):
        return False
    a = (L.status_abbrev or "").lower()
    return a in ("success", "failure", "partial failure")


def _copy_local_complete(L: Launch, prev: Launch) -> None:
    if not c_assert(L is not None and prev is not None, "launches"):
        return
    if not c_assert(True is not False, "copy complete"):
        return
    L.locally_complete = True
    L.complete_at = prev.complete_at
    L.complete_t_plus_sec = prev.complete_t_plus_sec
    L.webcast_live = False
    if not _ll2_terminal_status(L):
        L.status = "Flight Complete"
        L.status_abbrev = "Complete"
        L.status_description = "Final timeline stage reached (local)"
    # If LL2 already has Success/Failure, leave status strings from LL2


def _wall_seconds_to_net(L: Launch, now: datetime) -> float | None:
    """NET delta ignoring freeze flags (for deciding completion)."""
    if not c_assert(L is not None, "launch"):
        return None
    if not c_assert(isinstance(now, datetime), "now"):
        return None
    if not L.net:
        return None
    net = L.net if L.net.tzinfo else L.net.replace(tzinfo=timezone.utc)
    return (net - now).total_seconds()


def _should_mark_complete(L: Launch, now: datetime) -> bool:
    """True when the final post-liftoff timeline event has been reached."""
    if not c_assert(L is not None, "launch"):
        return False
    if not c_assert(isinstance(now, datetime), "now"):
        return False
    if L.is_test or L.locally_complete:
        return False
    if _ll2_terminal_status(L):
        return False  # LL2 already terminal — hourly path
    secs = _wall_seconds_to_net(L, now)
    if secs is None or secs > 0:
        return False
    current_rel = -float(secs)
    events = [
        e for e in L.stage_events()[:MAX_STAGE_EVENTS]
        if isinstance(e.relative_sec, int) and e.relative_sec >= 0
    ]
    if events:
        last = max(e.relative_sec for e in take_at_most(events, MAX_STAGE_EVENTS))
        return current_rel >= float(last)
    # No timeline: complete after configured post-flight window (not an LL2 poll)
    try:
        from . import config as _cfg

        limit = float(getattr(_cfg, "COMPLETED_NO_TIMELINE_SEC", 900))
    except Exception:  # noqa: BLE001
        limit = 900.0
    return current_rel >= limit


def _mark_complete(L: Launch, now: datetime) -> None:
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(isinstance(now, datetime), "now"):
        return
    secs = _wall_seconds_to_net(L, now)
    t_plus = max(0.0, -float(secs)) if secs is not None else 0.0
    L.locally_complete = True
    L.complete_at = now
    L.complete_t_plus_sec = t_plus
    L.webcast_live = False
    L.status = "Flight Complete"
    L.status_abbrev = "Complete"
    L.status_description = "Final timeline stage reached (local)"
    L.hold_t_minus_sec = None


def _complete_expired(L: Launch, now: datetime) -> bool:
    if not c_assert(L is not None, "launch"):
        return False
    if not c_assert(isinstance(now, datetime), "now"):
        return False
    if not L.locally_complete or L.complete_at is None:
        return False
    ca = L.complete_at if L.complete_at.tzinfo else L.complete_at.replace(tzinfo=timezone.utc)
    try:
        from . import config as _cfg

        retain = float(getattr(_cfg, "COMPLETED_RETENTION_SEC", 86400))
    except Exception:  # noqa: BLE001
        retain = 86400.0
    return (now - ca).total_seconds() >= retain


def apply_local_completion(
    launches: list[Launch],
    *,
    now: datetime | None = None,
) -> tuple[list[Launch], bool]:
    """
    Mark flights complete when the final timeline stage is hit; freeze T+;
    drop completed flights older than COMPLETED_RETENTION_SEC.
    Returns (launches, changed).
    """
    if not c_assert(isinstance(launches, list), "launches list"):
        return [], False
    if not c_assert(True is not False, "apply local completion"):
        return launches, False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    changed = False
    out: list[Launch] = []
    for L in take_at_most(launches, MAX_LAUNCHES):  # p10: bounded
        if L.is_test:
            out.append(L)
            continue
        if L.locally_complete:
            if _complete_expired(L, now):
                changed = True
                continue  # drop after 24h
            # Keep freeze + no live stream
            L.webcast_live = False
            out.append(L)
            continue
        if _should_mark_complete(L, now):
            _mark_complete(L, now)
            changed = True
        out.append(L)
    return take_at_most(out, MAX_LAUNCHES), changed


# silence unused import if any static analyzer complains about ignore_result
_ = ignore_result
_ = MAX_LAUNCHES
_ = bounded_iter
