"""Desktop notifications for upcoming launches (notify-send / mako)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone

from . import config
from .cache import load_notify_state, save_notify_state
from .models import Launch

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
    """
    Fire a desktop notification.
    If url is set, append it to the body (mako/sway often don't support action buttons well).
    """
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


def check_and_notify(launches: list[Launch], now: datetime | None = None) -> list[str]:
    """
    Send notifications for threshold crossings.
    Returns list of notification keys that were fired.
    """
    now = now or datetime.now(timezone.utc)
    state = load_notify_state()
    sent: dict = state.setdefault("sent", {})
    fired: list[str] = []

    # Only consider truly upcoming (not already successful hours ago)
    candidates = [L for L in launches if L.is_upcoming(now)]

    for L in candidates:
        secs = L.seconds_to_net(now)
        if secs is None:
            continue

        # Webcast live notification
        if L.webcast_live:
            key = f"{L.id}:live"
            if key not in sent:
                stream = L.primary_stream()
                url = stream.url if stream else None
                send_notification(
                    "🔴 LIVE: Launch webcast",
                    f"{L.name}\n{L.provider} · {L.location}",
                    urgency="critical",
                    expire_ms=0,
                    url=url,
                )
                sent[key] = now.isoformat()
                fired.append(key)

        # Threshold notifications (only while still counting down)
        if secs < 0:
            continue

        for threshold, label in config.NOTIFY_THRESHOLDS:
            if secs <= threshold:
                key = f"{L.id}:{label}"
                if key in sent:
                    continue
                # Only fire if we're not *way* past the window (e.g. app started at T-10m
                # shouldn't also fire T-24h). Fire if within 20% of threshold or 10 min slack.
                slack = max(threshold * 0.2, 600)
                if secs < threshold - slack and threshold > 900:
                    # Missed this window entirely (daemon was down); mark as sent without notify
                    sent[key] = now.isoformat()
                    continue

                stream = L.primary_stream()
                url = stream.url if stream else None
                net_local = ""
                if L.net:
                    # Local time for the human
                    net_local = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z")

                urgency = "critical" if threshold <= 15 * 60 else "normal"
                body_lines = [
                    f"{L.name}",
                    f"{label}  ·  NET {net_local}",
                    f"{L.provider}  ·  {L.pad}, {L.location}".strip(" ·"),
                ]
                if L.status:
                    body_lines.append(f"Status: {L.status_abbrev or L.status}")
                if L.probability is not None:
                    body_lines.append(f"Weather go: {L.probability}%")

                send_notification(
                    f"🚀 Launch {label}",
                    "\n".join(body_lines),
                    urgency=urgency,
                    expire_ms=0 if threshold <= 15 * 60 else 30000,
                    url=url,
                )
                sent[key] = now.isoformat()
                fired.append(key)

    # Prune old keys (keep last ~500)
    if len(sent) > 500:
        # Keep newest by value timestamp when possible
        items = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)
        state["sent"] = dict(items[:400])
    else:
        state["sent"] = sent

    save_notify_state(state)
    return fired
