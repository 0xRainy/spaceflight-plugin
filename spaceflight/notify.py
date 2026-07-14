"""Desktop notifications for upcoming launches and flight stages."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone

from . import config
from .cache import load_notify_state, save_notify_state
from .models import Launch, TimelineEvent

log = logging.getLogger("spaceflight.notify")


def _notify_send_available() -> bool:
    return shutil.which("notify-send") is not None


def send_notification(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    expire_ms: int | None = None,
    url: str | None = None,
) -> bool:
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
    return stream.url if stream else None


def _notify_stage(L: Launch, event: TimelineEvent, now: datetime) -> None:
    phase = "COUNTDOWN" if event.relative_sec < 0 else "FLIGHT STAGE"
    title = f"🚀 {event.label_t()} · {phase}"
    body_lines = [
        L.name,
        event.description,
        f"{L.provider} · {L.pad}, {L.location}".strip(" ·"),
    ]
    if L.mission_brief and L.mission_brief.title:
        body_lines.insert(1, L.mission_brief.title)
    # Critical near liftoff / during early flight
    urgency = "critical" if abs(event.relative_sec) <= 180 or event.relative_sec >= 0 else "normal"
    send_notification(
        title,
        "\n".join(body_lines),
        urgency=urgency,
        expire_ms=0 if urgency == "critical" else 20000,
        url=_stream_url(L),
    )


def check_and_notify(launches: list[Launch], now: datetime | None = None) -> list[str]:
    """
    Threshold countdowns + per-stage timeline events when data exists.
    Returns list of notification keys that were fired.
    """
    now = now or datetime.now(timezone.utc)
    state = load_notify_state()
    sent: dict = state.setdefault("sent", {})
    fired: list[str] = []

    # Keep launches that are soon or recently flown (for stage events up to ~2h)
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

        # Webcast live
        if L.webcast_live:
            key = f"{L.id}:live"
            if key not in sent:
                send_notification(
                    "🔴 LIVE: Launch webcast",
                    f"{L.name}\n{L.provider} · {L.location}",
                    urgency="critical",
                    expire_ms=0,
                    url=_stream_url(L),
                )
                sent[key] = now.isoformat()
                fired.append(key)

        # Classic T-minus thresholds (pre-launch only)
        if secs >= 0:
            for threshold, label in config.NOTIFY_THRESHOLDS:
                if secs <= threshold:
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
                    # Hint next timeline stage
                    nxt = L.next_stage(now)
                    if nxt and nxt.relative_sec < 0:
                        body_lines.append(f"Next: {nxt.label_t()} {nxt.description[:80]}")
                    send_notification(
                        f"🚀 Launch {label}",
                        "\n".join(body_lines),
                        urgency=urgency,
                        expire_ms=0 if threshold <= 15 * 60 else 30000,
                        url=_stream_url(L),
                    )
                    sent[key] = now.isoformat()
                    fired.append(key)

        # ── Stage events (countdown milestones + flight stages) ──
        # current_rel: seconds after NET (negative before)
        current_rel = -secs
        for event in L.stage_events():
            # Fire once we've reached/passed the event time
            if current_rel < event.relative_sec:
                continue
            key = f"{L.id}:stage:{event.relative_sec}:{event.description[:40]}"
            if key in sent:
                continue
            # Missed by more than 3 minutes → mark silently (daemon was down)
            overdue = current_rel - event.relative_sec
            if overdue > 180:
                sent[key] = now.isoformat()
                continue
            # Don't spam ancient pre-launch events if we just started far from NET
            # (e.g. starting app at T-1h shouldn't fire T-50m prop load if already past)
            # already handled by overdue > 180 for events 3+ min past

            _notify_stage(L, event, now)
            sent[key] = now.isoformat()
            fired.append(key)

    # Prune
    if len(sent) > 800:
        items = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)
        state["sent"] = dict(items[:500])
    else:
        state["sent"] = sent

    save_notify_state(state)
    return fired
