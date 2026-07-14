"""Desktop + phone notifications for upcoming launches and flight stages."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone

import requests

from . import config
from .cache import load_notify_state, save_notify_state
from .models import Launch, TimelineEvent
from .settings import Settings, load_settings

log = logging.getLogger("spaceflight.notify")


def _notify_send_available() -> bool:
    return shutil.which("notify-send") is not None


def send_desktop(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    expire_ms: int | None = None,
    url: str | None = None,
    enabled: bool = True,
) -> bool:
    if not enabled:
        return False
    if not _notify_send_available():
        log.warning("notify-send not found")
        return False

    if url:
        body = f"{body}\n\n▶ Watch: {url}"

    cmd = [
        "notify-send",
        "--app-name=Spaceflight",
        f"--urgency={urgency}",
        "--icon=rocket",
        "--category=space.launch",
    ]
    if expire_ms is not None:
        cmd.append(f"--expire-time={expire_ms}")
    cmd.extend([title, body])

    try:
        subprocess.run(cmd, check=False, timeout=5)
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("notify-send failed: %s", exc)
        return False


# Back-compat name
def send_notification(*args, **kwargs) -> bool:
    settings = load_settings()
    kwargs.setdefault("enabled", settings.desktop_enabled)
    return send_desktop(*args, **kwargs)


def send_phone(
    title: str,
    body: str,
    *,
    settings: Settings | None = None,
    click_url: str | None = None,
    tags: str = "rocket",
    priority: int = 4,
) -> bool:
    """
    Push to phone via ntfy (https://ntfy.sh).
    Free: install the ntfy app and subscribe to your private topic.
    """
    settings = settings or load_settings()
    topic = (settings.ntfy_topic or "").strip()
    if not topic:
        return False

    server = (settings.ntfy_server or "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    headers = {
        "Title": title[:250],
        "Priority": str(max(1, min(5, priority))),
        "Tags": tags,
        "User-Agent": config.USER_AGENT,
    }
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {settings.ntfy_token}"
    if click_url:
        headers["Click"] = click_url
        headers["Actions"] = f"view, Watch, {click_url}, clear=true"

    try:
        r = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=15)
        if r.status_code >= 400:
            log.warning("ntfy push HTTP %s: %s", r.status_code, r.text[:200])
            return False
        log.info("ntfy push ok → %s", topic[:12] + "…")
        return True
    except requests.RequestException as exc:
        log.warning("ntfy push failed: %s", exc)
        return False


def open_url(url: str) -> None:
    if not url:
        return
    opener = shutil.which("xdg-open") or shutil.which("firefox") or shutil.which("chromium")
    if not opener:
        return
    try:
        subprocess.Popen(  # noqa: S603
            [opener, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def _stream_url(L: Launch) -> str | None:
    stream = L.primary_stream()
    if stream:
        return stream.url
    if L.mission_brief and L.mission_brief.page_url:
        return L.mission_brief.page_url
    if L.info_urls:
        return L.info_urls[0]
    return None


def _phone_t24h_body(L: Launch) -> tuple[str, str, str | None]:
    """Build T-24h phone notification content."""
    mission = L.short_name() or L.name
    vehicle = L.vehicle_name()
    location = ", ".join(p for p in (L.pad, L.location) if p) or "TBD"
    if L.net:
        t0_local = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        t0_utc = L.net.strftime("%Y-%m-%d %H:%M UTC")
        t0 = f"{t0_local}\n({t0_utc})"
    else:
        t0 = "NET TBD"

    watch = _stream_url(L)
    title = f"🚀 Launch tomorrow: {mission}"
    lines = [
        f"Mission:  {mission}",
        f"Vehicle:  {vehicle}",
        f"Location: {location}",
        f"T-0:      {t0}",
        f"Provider: {L.provider or '—'}",
        f"Status:   {L.status_abbrev or L.status or '—'}",
    ]
    if watch:
        lines.append(f"Watch:    {watch}")
    if L.mission_brief and L.mission_brief.page_url:
        lines.append(f"Info:     {L.mission_brief.page_url}")
    return title, "\n".join(lines), watch


def _notify_stage(L: Launch, event: TimelineEvent, settings: Settings) -> None:
    phase = "COUNTDOWN" if event.relative_sec < 0 else "FLIGHT STAGE"
    title = f"🚀 {event.label_t()} · {phase}"
    body_lines = [
        L.name,
        event.description,
        f"{L.provider} · {L.pad}, {L.location}".strip(" ·"),
    ]
    if L.mission_brief and L.mission_brief.title:
        body_lines.insert(1, L.mission_brief.title)
    urgency = "critical" if abs(event.relative_sec) <= 180 or event.relative_sec >= 0 else "normal"
    send_desktop(
        title,
        "\n".join(body_lines),
        urgency=urgency,
        expire_ms=0 if urgency == "critical" else 20000,
        url=_stream_url(L),
        enabled=settings.desktop_enabled,
    )


def check_and_notify(launches: list[Launch], now: datetime | None = None) -> list[str]:
    """
    Threshold countdowns + per-stage events (desktop).
    Phone (ntfy): T-24h only with mission/vehicle/location/T-0/watch link.
    """
    now = now or datetime.now(timezone.utc)
    settings = load_settings()
    state = load_notify_state()
    sent: dict = state.setdefault("sent", {})
    fired: list[str] = []

    candidates = []
    for L in launches:
        secs = L.seconds_to_net(now)
        if secs is None:
            continue
        if -2 * 3600 <= secs <= 48 * 3600:
            candidates.append(L)

    for L in candidates:
        secs = L.seconds_to_net(now)
        if secs is None:
            continue

        # Webcast live (desktop)
        if L.webcast_live:
            key = f"{L.id}:live"
            if key not in sent:
                send_desktop(
                    "🔴 LIVE: Launch webcast",
                    f"{L.name}\n{L.provider} · {L.location}",
                    urgency="critical",
                    expire_ms=0,
                    url=_stream_url(L),
                    enabled=settings.desktop_enabled,
                )
                sent[key] = now.isoformat()
                fired.append(key)

        # Classic T-minus thresholds
        if secs >= 0:
            for threshold, label in config.NOTIFY_THRESHOLDS:
                if secs > threshold:
                    continue
                key = f"{L.id}:{label}"
                if key in sent:
                    continue
                slack = max(threshold * 0.2, 600)
                if secs < threshold - slack and threshold > 900:
                    sent[key] = now.isoformat()
                    continue

                net_local = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else ""
                urgency = "critical" if threshold <= 15 * 60 else "normal"
                body_lines = [
                    f"{L.name}",
                    f"{label}  ·  NET {net_local}",
                    f"{L.provider}  ·  {L.pad}, {L.location}".strip(" ·"),
                ]
                if L.status:
                    body_lines.append(f"Status: {L.status_abbrev or L.status}")
                nxt = L.next_stage(now)
                if nxt and nxt.relative_sec < 0:
                    body_lines.append(f"Next: {nxt.label_t()} {nxt.description[:80]}")

                send_desktop(
                    f"🚀 Launch {label}",
                    "\n".join(body_lines),
                    urgency=urgency,
                    expire_ms=0 if threshold <= 15 * 60 else 30000,
                    url=_stream_url(L),
                    enabled=settings.desktop_enabled,
                )

                # Phone: only the T-24h alert (user request)
                if label == "T-24h" and settings.phone_enabled:
                    ptitle, pbody, watch = _phone_t24h_body(L)
                    phone_key = f"{L.id}:phone:T-24h"
                    if phone_key not in sent:
                        ok = send_phone(
                            ptitle,
                            pbody,
                            settings=settings,
                            click_url=watch,
                            tags="rocket,warning",
                            priority=4,
                        )
                        if ok:
                            sent[phone_key] = now.isoformat()
                            fired.append(phone_key)

                sent[key] = now.isoformat()
                fired.append(key)

        # Stage events (desktop only — too chatty for phone)
        current_rel = -secs
        for event in L.stage_events():
            if current_rel < event.relative_sec:
                continue
            key = f"{L.id}:stage:{event.relative_sec}:{event.description[:40]}"
            if key in sent:
                continue
            overdue = current_rel - event.relative_sec
            if overdue > 180:
                sent[key] = now.isoformat()
                continue
            _notify_stage(L, event, settings)
            sent[key] = now.isoformat()
            fired.append(key)

    if len(sent) > 800:
        items = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)
        state["sent"] = dict(items[:500])
    else:
        state["sent"] = sent

    save_notify_state(state)
    return fired


def test_phone_push() -> bool:
    """Send a sample T-24h-style phone notification."""
    settings = load_settings()
    if not settings.phone_enabled:
        return False
    return send_phone(
        "🚀 Spaceflight phone test",
        "If you see this, ntfy is wired up.\n"
        "You'll get a push ~24h before each launch with mission, vehicle, location, T-0, and watch link.",
        settings=settings,
        tags="white_check_mark,rocket",
        priority=3,
    )
