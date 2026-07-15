"""Desktop + phone notifications for upcoming launches and flight stages."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config
from .cache import ensure_dirs, load_notify_state, save_notify_state
from .models import Launch, TimelineEvent
from .settings import Settings, load_settings

log = logging.getLogger("spaceflight.notify")


def _notify_send_available() -> bool:
    return shutil.which("notify-send") is not None


def open_spaceflight_app() -> None:
    """Open the Spaceflight TUI (same path as Waybar left-click)."""
    term = (
        shutil.which("xdg-terminal-exec")
        or shutil.which("ghostty")
        or shutil.which("kitty")
        or shutil.which("alacritty")
    )
    sf = shutil.which("spaceflight")
    try:
        if term and sf:
            if Path(term).name == "xdg-terminal-exec":
                subprocess.Popen(  # noqa: S603
                    [term, "-e", sf],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            elif Path(term).name == "ghostty":
                subprocess.Popen(  # noqa: S603
                    [term, "-e", sf],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:
                subprocess.Popen(  # noqa: S603
                    [term, "-e", sf],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        elif sf:
            subprocess.Popen(  # noqa: S603
                [sf],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            log.warning("spaceflight binary not on PATH — cannot open app")
    except OSError as exc:
        log.warning("open_spaceflight_app failed: %s", exc)


def send_desktop(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    expire_ms: int | None = None,
    url: str | None = None,
    enabled: bool = True,
    open_app_on_click: bool = True,
) -> bool:
    """
    Desktop notification via notify-send.
    With open_app_on_click=True (default), click/Open runs Spaceflight TUI
    (mako/libnotify actions + --wait in a background thread).
    """
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

    if open_app_on_click:
        # -A implies --wait; run in a thread so we don't block the daemon
        cmd.extend(["-A", "default=Open", "-A", "open=Open app"])
        cmd.extend([title, body])

        def _wait_and_open() -> None:
            try:
                r = subprocess.run(  # noqa: S603
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
                action = (r.stdout or "").strip().splitlines()
                action = action[-1].strip() if action else ""
                if action in ("default", "open", "0", "1"):
                    open_spaceflight_app()
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.warning("notify-send wait failed: %s", exc)

        threading.Thread(target=_wait_and_open, daemon=True, name="sf-notify").start()
        return True

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
    # HTTP headers must be latin-1; strip/replace non-ascii (emoji) from Title etc.
    def _hdr(s: str, limit: int = 250) -> str:
        return (s or "").encode("ascii", "replace").decode("ascii")[:limit]

    headers = {
        "Title": _hdr(title),
        "Priority": str(max(1, min(5, priority))),
        "Tags": _hdr(tags, 100),
        "User-Agent": _hdr(config.USER_AGENT, 200),
    }
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {_hdr(settings.ntfy_token, 500)}"
    if click_url:
        headers["Click"] = _hdr(click_url, 500)
        headers["Actions"] = _hdr(f"view, Watch, {click_url}, clear=true", 500)

    try:
        # Body can be full UTF-8 (emoji OK here)
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


def _phone_alert_body(L: Launch, label: str) -> tuple[str, str, str | None]:
    """Build phone notification: mission, vehicle, location, T-0, watch link."""
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
    headline = {
        "T-24h": f"Launch in 24 hours: {mission}",
        "T-1h": f"Launch in 1 hour: {mission}",
        "T-10m": f"Launch in 10 minutes: {mission}",
    }.get(label, f"Launch {label}: {mission}")

    lines = [
        f"When:     {label}",
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
    return headline, "\n".join(lines), watch


# Back-compat alias
def _phone_t24h_body(L: Launch) -> tuple[str, str, str | None]:
    return _phone_alert_body(L, "T-24h")


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
    Desktop: countdown thresholds + flight stages.
    Phone (ntfy): T-24h, T-1h, T-10m with mission/vehicle/location/T-0/watch.
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
        # Include up to ~26h out so T-24h has a chance to fire
        if -2 * 3600 <= secs <= 26 * 3600:
            candidates.append(L)

    for L in candidates:
        secs = L.seconds_to_net(now)
        if secs is None:
            continue

        # Test flight: desktop stages/thresholds OK for local testing; never phone
        is_test = bool(L.is_test) or L.id == config.TEST_FLIGHT_ID

        # Webcast live (desktop) — skip test (too spammy on every loop)
        if L.webcast_live and not is_test:
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

        # Classic T-minus thresholds (desktop always; phone never for test)
        if secs >= 0:
            for threshold, label in config.NOTIFY_THRESHOLDS:
                if secs > threshold:
                    continue
                key = f"{L.id}:{label}"
                if key in sent:
                    continue
                # Missed window entirely (daemon was down) — mark without spam
                slack = max(threshold * 0.15, 120)
                # Test flight: only fire T-10m (not T-24h/T-1h ghosts on every loop)
                if is_test and label != "T-10m":
                    sent[key] = now.isoformat()
                    continue
                if secs < threshold - slack and threshold > 600:
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
                sent[key] = now.isoformat()
                fired.append(key)

            # Phone pushes: T-24h / T-1h / T-10m (never for test flight)
            if settings.phone_enabled and not is_test:
                for threshold, label in config.PHONE_NOTIFY_THRESHOLDS:
                    if secs > threshold:
                        continue
                    phone_key = f"{L.id}:phone:{label}"
                    if phone_key in sent:
                        continue
                    slack = max(threshold * 0.15, 120)
                    if secs < threshold - slack and threshold > 600:
                        sent[phone_key] = now.isoformat()
                        continue

                    ptitle, pbody, watch = _phone_alert_body(L, label)
                    priority = 5 if label == "T-10m" else (4 if label == "T-1h" else 3)
                    tags = {
                        "T-24h": "rocket,calendar",
                        "T-1h": "rocket,warning",
                        "T-10m": "rocket,rotating_light",
                    }.get(label, "rocket")
                    ok = send_phone(
                        ptitle,
                        pbody,
                        settings=settings,
                        click_url=watch,
                        tags=tags,
                        priority=priority,
                    )
                    if ok:
                        sent[phone_key] = now.isoformat()
                        fired.append(phone_key)

        # Stage events (desktop) — include TEST FLIGHT so you can verify stages
        current_rel = -secs
        for event in L.stage_events():
            if current_rel < event.relative_sec:
                continue
            # Per-cycle key for test flight so stages re-notify each loop
            if is_test and L.net:
                cycle = L.net.strftime("%Y%m%d%H%M%S")
                key = f"{L.id}:stage:{cycle}:{event.relative_sec}:{event.description[:40]}"
            else:
                key = f"{L.id}:stage:{event.relative_sec}:{event.description[:40]}"
            if key in sent:
                continue
            overdue = current_rel - event.relative_sec
            # Test flight: tight window so we don't dump the whole timeline on open
            max_overdue = 45 if is_test else 180
            if overdue > max_overdue:
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
        "Spaceflight phone test",
        "If you see this, ntfy is wired up.\n"
        "You'll get a push ~24h before each launch with mission, vehicle, location, T-0, and watch link.",
        settings=settings,
        tags="white_check_mark,rocket",
        priority=3,
    )


# ── New-flight detection ────────────────────────────────────

def _load_known_ids() -> set[str] | None:
    """None = never seeded (first run — seed without notifying)."""
    path = config.KNOWN_LAUNCHES
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data.get("ids")
        if isinstance(ids, list):
            return {str(i) for i in ids}
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return None


def _save_known_ids(ids: set[str]) -> None:
    ensure_dirs()
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ids": sorted(ids),
    }
    config.KNOWN_LAUNCHES.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _real_launches(launches: list[Launch]) -> list[Launch]:
    return [
        L
        for L in launches
        if L.id and not L.is_test and L.id != config.TEST_FLIGHT_ID
    ]


def notify_new_flights(launches: list[Launch]) -> list[str]:
    """
    Compare current launch IDs to the last known set.
    On first run, seed the set silently (no flood).
    On later refreshes, notify desktop + phone for each new id.
    """
    settings = load_settings()
    real = _real_launches(launches)
    current_ids = {L.id for L in real}
    known = _load_known_ids()

    if known is None:
        # First seed — do not notify for the whole catalog
        _save_known_ids(current_ids)
        log.info("Seeded known launches (%d) without notifying", len(current_ids))
        return []

    new_ids = current_ids - known
    # Drop IDs that disappeared from the upcoming list (keep set from growing forever)
    # but retain recently seen so reappearing NET shifts don't re-notify
    pruned = known & current_ids
    # Also keep a small history of gone IDs? For simplicity merge current only
    # so a flight that left and came back would re-notify — that's OK / rare.
    updated = current_ids | known  # remember everything we've ever seen
    # Cap memory: keep current + last ~500 known
    if len(updated) > 800:
        # Prefer keeping current + newest from known file order
        updated = current_ids | set(list(known)[-400:])
    _save_known_ids(updated)

    if not new_ids:
        return []

    by_id = {L.id: L for L in real}
    fired: list[str] = []
    for lid in sorted(new_ids):
        L = by_id.get(lid)
        if not L:
            continue
        mission = L.short_name() or L.name
        vehicle = L.vehicle_name()
        net_s = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else "NET TBD"
        loc = ", ".join(p for p in (L.pad, L.location) if p) or "—"
        body = "\n".join(
            [
                f"Mission:  {mission}",
                f"Vehicle:  {vehicle}",
                f"Provider: {L.provider or '—'}",
                f"Location: {loc}",
                f"NET:      {net_s}",
                f"Status:   {L.status_abbrev or L.status or '—'}",
                "",
                "Click to open Spaceflight",
            ]
        )
        title = f"New flight added · {mission}"

        send_desktop(
            title,
            body,
            urgency="normal",
            expire_ms=0,
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=True,
        )
        fired.append(f"{lid}:new_flight:desktop")

        if settings.phone_enabled:
            phone_body = "\n".join(
                [
                    f"Mission:  {mission}",
                    f"Vehicle:  {vehicle}",
                    f"Provider: {L.provider or '—'}",
                    f"Location: {loc}",
                    f"NET:      {net_s}",
                    f"Status:   {L.status_abbrev or L.status or '—'}",
                ]
            )
            ok = send_phone(
                f"New flight: {mission}",
                phone_body,
                settings=settings,
                click_url=_stream_url(L) or (L.mission_brief.page_url if L.mission_brief else None),
                tags="rocket,new",
                priority=3,
            )
            if ok:
                fired.append(f"{lid}:new_flight:phone")

        log.info("New flight notified: %s", L.name)

    return fired
