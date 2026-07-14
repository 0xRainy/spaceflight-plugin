"""Domain models for launches, streams, and vehicle/payload stats."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Handle both Z and +00:00
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _g(d: dict | None, *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


@dataclass
class StreamLink:
    title: str
    url: str
    publisher: str = ""
    source: str = ""
    stream_type: str = ""
    priority: int = 99

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> StreamLink:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class UpdateNote:
    comment: str
    created_by: str = ""
    created_on: datetime | None = None
    info_url: str = ""

    def to_dict(self) -> dict:
        return {
            "comment": self.comment,
            "created_by": self.created_by,
            "created_on": self.created_on.isoformat() if self.created_on else None,
            "info_url": self.info_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UpdateNote:
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
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BoosterInfo:
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
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> VehicleStats:
        boosters = [BoosterInfo.from_dict(b) for b in (d.get("boosters") or [])]
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
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PayloadStats:
        return cls(
            name=d.get("name") or "",
            type=d.get("type") or "",
            description=d.get("description") or "",
            orbit=d.get("orbit") or "",
            orbit_abbrev=d.get("orbit_abbrev") or "",
            agencies=list(d.get("agencies") or []),
        )


@dataclass
class WeatherInfo:
    summary: str = ""
    temp_f: str = ""
    condition: str = ""
    wind_mph: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> WeatherInfo:
        return cls(**{k: d.get(k) or "" for k in cls.__dataclass_fields__})


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

    # ── derived ──────────────────────────────────────────────

    def seconds_to_net(self, now: datetime | None = None) -> float | None:
        if not self.net:
            return None
        now = now or datetime.now(timezone.utc)
        return (self.net - now).total_seconds()

    def is_upcoming(self, now: datetime | None = None) -> bool:
        """True if still relevant as an upcoming / in-progress launch."""
        now = now or datetime.now(timezone.utc)
        abb = (self.status_abbrev or self.status or "").lower()
        if abb in ("success", "failure", "partial failure"):
            # Keep briefly after NET for status display
            secs = self.seconds_to_net(now)
            return secs is not None and secs > -3600
        secs = self.seconds_to_net(now)
        if secs is None:
            return True
        # Show past NET for a few hours if still "In Flight" etc.
        return secs > -6 * 3600

    def is_go(self) -> bool:
        a = (self.status_abbrev or "").lower()
        return a in ("go",) or "go for launch" in (self.status or "").lower()

    def is_hold(self) -> bool:
        a = (self.status_abbrev or "").lower()
        return "hold" in a or "hold" in (self.status or "").lower()

    def is_tbd(self) -> bool:
        a = (self.status_abbrev or "").lower()
        return a in ("tbd", "tbc")

    def is_live_or_inflight(self) -> bool:
        if self.webcast_live:
            return True
        a = (self.status_abbrev or self.status or "").lower()
        return a in ("in flight", "liftoff") or "in flight" in a

    def primary_stream(self) -> StreamLink | None:
        if not self.streams:
            return None
        return sorted(self.streams, key=lambda s: s.priority)[0]

    def countdown_label(self, now: datetime | None = None) -> str:
        secs = self.seconds_to_net(now)
        if secs is None:
            return "NET TBD"
        if self.is_live_or_inflight() and secs <= 0:
            return "LIFTOFF" if secs > -120 else f"T+{_fmt_duration(-secs)}"
        if secs < 0:
            abb = (self.status_abbrev or "").lower()
            if abb in ("success",):
                return "SUCCESS"
            if "fail" in abb:
                return "FAILURE"
            return f"T+{_fmt_duration(-secs)}"
        return f"T-{_fmt_duration(secs)}"

    def short_name(self) -> str:
        # Prefer "Vehicle | Mission" split
        if " | " in self.name:
            return self.name.split(" | ", 1)[1]
        return self.name

    def vehicle_name(self) -> str:
        if " | " in self.name:
            return self.name.split(" | ", 1)[0]
        return self.vehicle.full_name or self.vehicle.name or "?"

    def to_dict(self) -> dict:
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
            "latitude": self.latitude,
            "longitude": self.longitude,
            "vehicle": self.vehicle.to_dict(),
            "payload": self.payload.to_dict(),
            "streams": [s.to_dict() for s in self.streams],
            "updates": [u.to_dict() for u in self.updates],
            "image_url": self.image_url,
            "flightclub_url": self.flightclub_url,
            "slug": self.slug,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "weather": self.weather.to_dict() if self.weather else None,
            "programs": self.programs,
            "mission_patches": self.mission_patches,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Launch:
        weather = d.get("weather")
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
            streams=[StreamLink.from_dict(s) for s in (d.get("streams") or [])],
            updates=[UpdateNote.from_dict(u) for u in (d.get("updates") or [])],
            image_url=d.get("image_url") or "",
            flightclub_url=d.get("flightclub_url") or "",
            slug=d.get("slug") or "",
            last_updated=_parse_dt(d.get("last_updated")),
            weather=WeatherInfo.from_dict(weather) if weather else None,
            programs=list(d.get("programs") or []),
            mission_patches=list(d.get("mission_patches") or []),
            source=d.get("source") or "ll2",
        )


def _fmt_duration(seconds: float) -> str:
    s = int(abs(seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}h {mins:02d}m"
    if hours > 0:
        return f"{hours:02d}h {mins:02d}m {secs:02d}s"
    if mins > 0:
        return f"{mins:02d}m {secs:02d}s"
    return f"{secs:02d}s"


def parse_ll2_launch(raw: dict) -> Launch:
    """Convert a Launch Library 2 detailed launch object into a Launch."""
    status = raw.get("status") or {}
    lsp = raw.get("launch_service_provider") or {}
    rocket = raw.get("rocket") or {}
    cfg = rocket.get("configuration") or {}
    mission = raw.get("mission") or {}
    pad = raw.get("pad") or {}
    loc = pad.get("location") or {}
    orbit = mission.get("orbit") or {}
    net_prec = raw.get("net_precision") or {}

    # Streams: LL2 uses vidURLs (camelCase)
    streams: list[StreamLink] = []
    for v in raw.get("vidURLs") or raw.get("vid_urls") or []:
        if isinstance(v, str):
            streams.append(StreamLink(title="Webcast", url=v))
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
    streams = [s for s in streams if s.url]

    updates: list[UpdateNote] = []
    for u in raw.get("updates") or []:
        updates.append(
            UpdateNote(
                comment=u.get("comment") or "",
                created_by=u.get("created_by") or "",
                created_on=_parse_dt(u.get("created_on")),
                info_url=u.get("info_url") or "",
            )
        )

    boosters: list[BoosterInfo] = []
    for stage in rocket.get("launcher_stage") or []:
        launcher = stage.get("launcher") or {}
        landing = stage.get("landing") or {}
        land_loc = landing.get("location") or {}
        land_type = landing.get("type") or {}
        prev = stage.get("previous_flight") or {}
        boosters.append(
            BoosterInfo(
                serial=launcher.get("serial_number") or "",
                flights=launcher.get("flights") if launcher.get("flights") is not None else stage.get("launcher_flight_number"),
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

    vehicle = VehicleStats(
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
        boosters=boosters,
    )

    agencies = []
    for a in mission.get("agencies") or []:
        if isinstance(a, dict) and a.get("name"):
            agencies.append(a["name"])
        elif isinstance(a, str):
            agencies.append(a)

    payload = PayloadStats(
        name=mission.get("name") or "",
        type=mission.get("type") or "",
        description=mission.get("description") or "",
        orbit=orbit.get("name") or "",
        orbit_abbrev=orbit.get("abbrev") or "",
        agencies=agencies,
    )

    programs = []
    for p in raw.get("program") or []:
        if isinstance(p, dict) and p.get("name"):
            programs.append(p["name"])

    patches = []
    for p in raw.get("mission_patches") or []:
        if isinstance(p, dict) and p.get("image_url"):
            patches.append(p["image_url"])
        elif isinstance(p, str):
            patches.append(p)

    image = raw.get("image")
    if isinstance(image, dict):
        image_url = image.get("image_url") or image.get("url") or ""
    else:
        image_url = image or ""

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
        vehicle=vehicle,
        payload=payload,
        streams=streams,
        updates=updates,
        image_url=image_url,
        flightclub_url=raw.get("flightclub_url") or "",
        slug=raw.get("slug") or "",
        last_updated=_parse_dt(raw.get("last_updated")),
        programs=programs,
        mission_patches=patches,
        source="ll2",
    )


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
