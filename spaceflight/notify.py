"""Desktop + phone notifications for upcoming launches and flight stages."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config
from .cache import ensure_dirs, load_notify_state, save_notify_state
from .models import Launch, TimelineEvent
from .p10 import (
    MAX_KNOWN_LAUNCH_IDS,
    MAX_LAUNCHES,
    MAX_NOTIFY_KEYS,
    MAX_STAGE_EVENTS,
    c_assert,
    ignore_result,
)
from .p10.bounds import take_at_most
from .settings import Settings, load_settings

log = logging.getLogger("spaceflight.notify")

_MAX_CANDIDATES = 32
_MAX_SCRIPT_CANDIDATES = 8
_MAX_PATH_EXTRAS = 8
_MAX_THRESHOLDS = 16
_MAX_NEW_FLIGHTS = 32
_MAX_BODY_LINES = 24
_MAX_NOTIFY_ACTION_LINES = 32


def _notify_send_available() -> bool:
    which = shutil.which("notify-send")
    if not c_assert(which is None or isinstance(which, str), "which type"):
        return False
    if not c_assert(True, "notify-send probe ok"):
        return False
    return which is not None


def _project_root() -> Path:
    # spaceflight/notify.py → package dir → repo root
    root = Path(__file__).resolve().parent.parent
    if not c_assert(root is not None, "root path"):
        return Path(".")
    if not c_assert(isinstance(root, Path), "root Path type"):
        return Path(".")
    return root


def resolve_spaceflight_script() -> Path | None:
    """
    Absolute path to the spaceflight launcher.

    Critical for the systemd user service, whose PATH often omits ~/.local/bin
    (notify clicks previously failed with "spaceflight binary not on PATH").
    """
    candidates: list[Path] = [
        Path.home() / ".local/bin" / "spaceflight",
        _project_root() / "scripts" / "spaceflight",
    ]
    which = shutil.which("spaceflight")
    if which:
        candidates.insert(0, Path(which))
    if not c_assert(len(candidates) > 0, "no script candidates"):
        return None
    for p in take_at_most(candidates, _MAX_SCRIPT_CANDIDATES):
        try:
            if p.is_file() and os.access(p, os.X_OK):
                if not c_assert(p is not None, "path resolved"):
                    return None
                return p.resolve()
        except OSError:
            continue
    return None


def _launch_env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(_project_root())
    local_bin = str(Path.home() / ".local" / "bin")
    path_parts = env.get("PATH", "/usr/bin:/bin").split(os.pathsep)
    extras = (local_bin, "/usr/local/bin", "/usr/bin", "/bin")
    if not c_assert(isinstance(path_parts, list), "PATH parts list"):
        path_parts = ["/usr/bin", "/bin"]
    for extra in take_at_most(list(extras), _MAX_PATH_EXTRAS):
        if extra and extra not in path_parts:
            path_parts.insert(0, extra)
    env["PATH"] = os.pathsep.join(path_parts)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{root}{os.pathsep}{prev}" if prev else root
    if "HOME" not in env:
        env["HOME"] = str(Path.home())
    if not c_assert("PATH" in env, "PATH must be set"):
        env["PATH"] = "/usr/bin:/bin"
    return env


def _try_omarchy_launch(script: Path, env: dict[str, str]) -> bool:
    """Launch via Omarchy TUI helpers when available."""
    if not c_assert(script is not None, "script required"):
        return False
    helpers = ("omarchy-launch-or-focus-tui", "omarchy-launch-tui")
    if not c_assert(len(helpers) >= 1, "helpers non-empty"):
        return False
    for helper in take_at_most(list(helpers), 4):
        helper_path = shutil.which(helper)
        if not helper_path:
            continue
        ignore_result(
            subprocess.Popen(  # noqa: S603
                [helper_path, str(script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        )
        log.info("open_spaceflight_app via %s %s", helper, script)
        return True
    return False


def _try_terminal_launch(script: Path, env: dict[str, str]) -> bool:
    """Launch spaceflight inside a terminal (optionally via uwsm-app)."""
    if not c_assert(script is not None, "script required"):
        return False
    term = (
        shutil.which("xdg-terminal-exec")
        or shutil.which("ghostty")
        or shutil.which("kitty")
        or shutil.which("alacritty")
        or shutil.which("foot")
    )
    if not term:
        return False
    uwsm = shutil.which("uwsm-app")
    inner = [term, "-e", str(script)]
    cmd = [uwsm, "--", *inner] if uwsm else inner
    if not c_assert(len(cmd) >= 2, "terminal command incomplete"):
        return False
    ignore_result(
        subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    )
    log.info("open_spaceflight_app via %s", " ".join(cmd))
    return True


def _try_direct_script(script: Path, env: dict[str, str]) -> bool:
    """Run the launcher binary/script directly."""
    if not c_assert(script is not None, "script required"):
        return False
    if not c_assert(os.access(script, os.X_OK) or script.is_file(), "script not usable"):
        return False
    ignore_result(
        subprocess.Popen(  # noqa: S603
            [str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    )
    log.info("open_spaceflight_app direct %s", script)
    return True


def _fallback_python_module(env: dict[str, str]) -> None:
    """Last resort: python -m spaceflight (may fail headless)."""
    root = _project_root()
    if not c_assert(root is not None, "project root missing"):
        return
    if not c_assert(sys.executable is not None, "no python executable"):
        return
    ignore_result(
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "spaceflight"],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    )
    log.warning("open_spaceflight_app fallback: python -m spaceflight")


def open_spaceflight_app() -> None:
    """Open the Spaceflight TUI (reliable from systemd + interactive shells)."""
    env = _launch_env()
    script = resolve_spaceflight_script()
    if not c_assert(isinstance(env, dict), "launch env must be dict"):
        return
    try:
        if script is not None and _try_omarchy_launch(script, env):
            return
        if script is not None and _try_terminal_launch(script, env):
            return
        if script is not None and _try_direct_script(script, env):
            return
        if not c_assert(isinstance(env, dict) and "PATH" in env, "env usable for fallback"):
            return
        _fallback_python_module(env)
    except OSError as exc:
        log.warning("open_spaceflight_app failed: %s", exc)


def _parse_notify_action(raw: str) -> str:
    """Extract action token from notify-send --wait stdout."""
    if not c_assert(raw is not None, "raw stdout None"):
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    limited = take_at_most(lines, _MAX_NOTIFY_ACTION_LINES)
    if not c_assert(isinstance(limited, list), "lines must be list"):
        return ""
    return limited[-1] if limited else ""


def _wait_and_open(cmd: list[str]) -> None:
    """Block on notify-send --wait; open TUI on Open action."""
    if not c_assert(isinstance(cmd, list) and len(cmd) >= 2, "notify cmd invalid"):
        return
    if not c_assert(cmd[0] == "notify-send", "expected notify-send"):
        return
    try:
        r = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
            env=_launch_env(),
        )
        action = _parse_notify_action((r.stdout or "").strip())
        if action.lower() in ("default", "open", "0", "1"):
            open_spaceflight_app()
        elif action:
            log.info("notify-send action ignored: %r", action)
        else:
            log.info("notify-send closed with no action (dismiss)")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("notify-send wait failed: %s", exc)


# Desktop toast policy:
# - Never use expire-time=0 (libnotify: never dismiss) for auto stages.
# - Avoid urgency=critical when we want auto-timeout (mako ignores expire for critical).
# - Replace stage toasts so only one is visible at a time.
_EXPIRE_MIN_MS = 5_000
_EXPIRE_MAX_MS = 45_000
_EXPIRE_DEFAULT_MS = 12_000
_EXPIRE_HOLD_MS = 25_000
_EXPIRE_THRESHOLD_MS = 20_000
_STAGE_REPLACE_ID_PATH = config.STATE_DIR / "notify_stage_replace_id"
# Shared slot for stage toasts (mako / libnotify replace)
_STAGE_SYNC_HINT = "spaceflight-stage"


def _clamp_expire_ms(ms: int) -> int:
    if not c_assert(isinstance(ms, (int, float)), "ms numeric"):
        return _EXPIRE_DEFAULT_MS
    if not c_assert(True is not False, "clamp expire"):
        return _EXPIRE_DEFAULT_MS
    return max(_EXPIRE_MIN_MS, min(_EXPIRE_MAX_MS, int(ms)))


def expire_ms_until_next_stage(
    L: Launch,
    now: datetime,
    *,
    current_rel: float | None = None,
    default_ms: int = _EXPIRE_DEFAULT_MS,
) -> int:
    """
    Timeout so this toast is gone before the next timeline stage fires.
    gap_sec − 2s buffer, clamped to [5s, 45s].
    """
    if not c_assert(L is not None, "launch"):
        return _clamp_expire_ms(default_ms)
    if not c_assert(now is not None, "now"):
        return _clamp_expire_ms(default_ms)
    if current_rel is None:
        secs = L.seconds_to_net(now)
        if secs is None:
            return _clamp_expire_ms(default_ms)
        current_rel = -float(secs)
    nxt = None
    for e in take_at_most(list(L.stage_events()), MAX_STAGE_EVENTS):  # p10: bounded
        if e.relative_sec > float(current_rel):
            nxt = e
            break
    if nxt is None:
        return _clamp_expire_ms(default_ms)
    gap = float(nxt.relative_sec) - float(current_rel)
    # Leave 2s before next stage; if gap is tiny, still show briefly
    ms = int(max(0.0, gap - 2.0) * 1000)
    if ms < _EXPIRE_MIN_MS:
        ms = min(_EXPIRE_MIN_MS, max(3_000, int(gap * 1000 * 0.7)))
    return _clamp_expire_ms(ms)


def _load_stage_replace_id() -> int | None:
    if not c_assert(True is not False, "load replace id"):
        return None
    if not c_assert(hasattr(config, "STATE_DIR"), "state dir"):
        return None
    path = _STAGE_REPLACE_ID_PATH
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None
    except (OSError, ValueError):
        return None


def _save_stage_replace_id(nid: int) -> None:
    if not c_assert(isinstance(nid, int) and nid > 0, "nid positive"):
        return
    if not c_assert(True is not False, "save replace id"):
        return
    try:
        ensure_dirs()
        path = _STAGE_REPLACE_ID_PATH
        path.write_text(str(nid), encoding="utf-8")
    except OSError as exc:
        log.debug("replace-id save failed: %s", exc)


def _build_notify_cmd(
    title: str,
    body: str,
    *,
    urgency: str,
    expire_ms: int | None,
    open_app_on_click: bool,
    replace_id: int | None = None,
    replace_tag: str | None = None,
    transient: bool = True,
    print_id: bool = False,
) -> list[str]:
    """Assemble notify-send argv."""
    if not c_assert(isinstance(title, str) and title, "title required"):
        title = "Spaceflight"
    if not c_assert(isinstance(body, str), "body must be str"):
        body = ""
    # Never pass 0 — that means "never expire" on most servers
    if expire_ms is not None and int(expire_ms) <= 0:
        expire_ms = _EXPIRE_DEFAULT_MS
    cmd = [
        "notify-send",
        "--app-name=Spaceflight",
        f"--urgency={urgency}",
        "--icon=rocket",
        "--category=space.launch",
    ]
    if transient:
        cmd.append("--transient")
    if expire_ms is not None:
        cmd.append(f"--expire-time={int(expire_ms)}")
    if replace_id is not None and replace_id > 0:
        cmd.extend(["--replace-id", str(int(replace_id))])
    if replace_tag:
        # Canonical / GNOME / mako: same tag replaces previous toast
        cmd.extend(["-h", f"string:x-canonical-private-synchronous:{replace_tag}"])
        cmd.extend(["-h", f"string:x-dunst-stack-tag:{replace_tag}"])
    if print_id:
        cmd.append("--print-id")
    if open_app_on_click:
        # NOTE: -A implies --wait; prefer False for auto-expiring stage toasts
        cmd.extend(["-A", "default=Open", "-A", "open=Open app"])
    cmd.extend([title, body])
    return cmd


def _normalize_expire_ms(expire_ms: int | None) -> int:
    if not c_assert(expire_ms is None or isinstance(expire_ms, (int, float)), "expire"):
        return _EXPIRE_DEFAULT_MS
    if not c_assert(True is not False, "normalize expire"):
        return _EXPIRE_DEFAULT_MS
    if expire_ms is None:
        return _EXPIRE_DEFAULT_MS
    if int(expire_ms) <= 0:
        return _EXPIRE_MAX_MS
    return int(expire_ms)


def _run_notify_cmd(cmd: list[str], *, replace_stage: bool) -> bool:
    if not c_assert(isinstance(cmd, list) and cmd, "cmd"):
        return False
    if not c_assert(isinstance(replace_stage, bool), "replace bool"):
        return False
    try:
        r = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=_launch_env(),
        )
        if replace_stage and r.stdout:
            line = (r.stdout or "").strip().splitlines()
            if line and line[0].strip().isdigit():
                _save_stage_replace_id(int(line[0].strip()))
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("notify-send failed: %s", exc)
        return False


def send_desktop(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    expire_ms: int | None = None,
    url: str | None = None,
    enabled: bool = True,
    open_app_on_click: bool = False,
    replace_stage: bool = False,
    transient: bool = True,
) -> bool:
    """
    Desktop notification via notify-send.

    Defaults favour auto-dismiss (transient + expire). Stage toasts use
    replace_stage=True so only one stage notification is visible at a time.
    open_app_on_click uses -A/--wait which can fight timeouts — leave off for stages.
    """
    if not enabled:
        return False
    if not _notify_send_available():
        log.warning("notify-send not found")
        return False
    if not c_assert(isinstance(title, str), "title must be str"):
        return False
    if not c_assert(isinstance(body, str), "body must be str"):
        return False
    if url:
        body = f"{body}\n\n▶ Watch: {url}"
    expire_ms = _normalize_expire_ms(expire_ms)
    # mako ignores expire-time for critical → force normal when we want timeout
    if urgency == "critical" and expire_ms < 120_000:
        urgency = "normal"
    cmd = _build_notify_cmd(
        title,
        body,
        urgency=urgency,
        expire_ms=expire_ms,
        open_app_on_click=open_app_on_click,
        replace_id=_load_stage_replace_id() if replace_stage else None,
        replace_tag=_STAGE_SYNC_HINT if replace_stage else None,
        transient=transient,
        print_id=replace_stage,
    )
    if open_app_on_click:
        threading.Thread(
            target=_wait_and_open, args=(cmd,), daemon=True, name="sf-notify",
        ).start()
        return True
    return _run_notify_cmd(cmd, replace_stage=replace_stage)


# Back-compat name
def send_notification(*args, **kwargs) -> bool:
    settings = load_settings()
    if not c_assert(settings is not None, "settings load failed"):
        return False
    kwargs.setdefault("enabled", settings.desktop_enabled)
    if not c_assert(isinstance(kwargs, dict), "kwargs dict"):
        return False
    return send_desktop(*args, **kwargs)


def _hdr_ascii(s: str, limit: int = 250) -> str:
    """HTTP headers must be latin-1; strip/replace non-ascii."""
    if not c_assert(limit > 0, "header limit positive"):
        return ""
    if not c_assert(isinstance(s, str) or s is None, "header value type"):
        return ""
    return (s or "").encode("ascii", "replace").decode("ascii")[:limit]


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
    if not c_assert(settings is not None, "settings required"):
        return False
    topic = (settings.ntfy_topic or "").strip()
    if not topic:
        return False
    if not c_assert(isinstance(title, str) and title, "phone title required"):
        return False

    server = (settings.ntfy_server or "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    headers = {
        "Title": _hdr_ascii(title),
        "Priority": str(max(1, min(5, priority))),
        "Tags": _hdr_ascii(tags, 100),
        "User-Agent": _hdr_ascii(config.USER_AGENT, 200),
    }
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {_hdr_ascii(settings.ntfy_token, 500)}"
    if click_url:
        headers["Click"] = _hdr_ascii(click_url, 500)
        headers["Actions"] = _hdr_ascii(f"view, Watch, {click_url}, clear=true", 500)

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
    if not c_assert(isinstance(url, str), "url must be str"):
        return
    opener = shutil.which("xdg-open") or shutil.which("firefox") or shutil.which("chromium")
    if not opener:
        return
    if not c_assert(opener is not None, "opener missing"):
        return
    try:
        ignore_result(
            subprocess.Popen(  # noqa: S603
                [opener, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )
    except OSError:
        pass


def _stream_url(L: Launch) -> str | None:
    if not c_assert(L is not None, "launch required"):
        return None
    stream = L.primary_stream()
    if stream:
        return stream.url
    if L.mission_brief and L.mission_brief.page_url:
        return L.mission_brief.page_url
    if L.info_urls:
        if not c_assert(len(L.info_urls) > 0, "info_urls empty after truthy"):
            return None
        return L.info_urls[0]
    return None


def _phone_alert_body(L: Launch, label: str) -> tuple[str, str, str | None]:
    """Build phone notification: mission, vehicle, location, T-0, watch link."""
    if not c_assert(L is not None, "launch required"):
        return "Launch", "", None
    if not c_assert(isinstance(label, str) and label, "label required"):
        label = "?"
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
    return headline, "\n".join(take_at_most(lines, _MAX_BODY_LINES)), watch


# Back-compat alias
def _phone_t24h_body(L: Launch) -> tuple[str, str, str | None]:
    if not c_assert(L is not None, "launch required"):
        return "Launch", "", None
    if not c_assert(True, "t24h alias"):
        return "Launch", "", None
    return _phone_alert_body(L, "T-24h")


def _notify_stage(
    L: Launch,
    event: TimelineEvent,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> None:
    if not c_assert(L is not None and event is not None, "stage args"):
        return
    if not c_assert(settings is not None, "settings required"):
        return
    now = now or datetime.now(timezone.utc)
    phase = "COUNTDOWN" if event.relative_sec < 0 else "FLIGHT STAGE"
    title = f"🚀 {event.label_t()} · {phase}"
    body_lines = [
        L.name,
        event.description,
        f"{L.provider} · {L.pad}, {L.location}".strip(" ·"),
    ]
    if L.mission_brief and L.mission_brief.title:
        body_lines.insert(1, L.mission_brief.title)
    # Expire before next stage so only one toast is up at a time
    expire = expire_ms_until_next_stage(
        L, now, current_rel=float(event.relative_sec), default_ms=_EXPIRE_DEFAULT_MS
    )
    ignore_result(
        send_desktop(
            title,
            "\n".join(take_at_most(body_lines, _MAX_BODY_LINES)),
            urgency="normal",
            expire_ms=expire,
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,  # -A/--wait fights auto-expire
            replace_stage=True,
            transient=True,
        )
    )


def _collect_candidates(launches: list[Launch], now: datetime) -> list[Launch]:
    """Launches within ~26h of NET (for T-24h through early post-liftoff)."""
    if not c_assert(isinstance(launches, list), "launches must be list"):
        return []
    if not c_assert(now is not None, "now required"):
        return []
    candidates: list[Launch] = []
    for L in take_at_most(launches, MAX_LAUNCHES):
        secs = L.seconds_to_net(now)
        if secs is None:
            continue
        if -2 * 3600 <= secs <= 26 * 3600:
            candidates.append(L)
            if len(candidates) >= _MAX_CANDIDATES:
                break
    return candidates


def _is_test_launch(L: Launch) -> bool:
    if not c_assert(L is not None, "launch required"):
        return False
    if not c_assert(hasattr(L, "is_test"), "launch shape"):
        return False
    return bool(L.is_test) or L.id == config.TEST_FLIGHT_ID


def _notify_webcast_live(
    L: Launch,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Desktop critical notice when webcast goes live (skip test flights)."""
    if not c_assert(L is not None and sent is not None, "live notify args"):
        return
    if not L.webcast_live or _is_test_launch(L):
        return
    key = f"{L.id}:live"
    if key in sent:
        return
    if not c_assert(isinstance(key, str), "key type"):
        return
    ignore_result(
        send_desktop(
            "🔴 LIVE: Launch webcast",
            f"{L.name}\n{L.provider} · {L.location}",
            urgency="normal",
            expire_ms=expire_ms_until_next_stage(L, now, default_ms=25_000),
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,
            replace_stage=True,
            transient=True,
        )
    )
    sent[key] = now.isoformat()
    fired.append(key)


def _desktop_threshold_body(L: Launch, label: str, now: datetime) -> str:
    """Body text for classic T-minus desktop thresholds."""
    if not c_assert(L is not None, "launch required"):
        return ""
    if not c_assert(isinstance(label, str), "label str"):
        label = "?"
    net_local = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else ""
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
    return "\n".join(take_at_most(body_lines, _MAX_BODY_LINES))


def _notify_desktop_thresholds(
    L: Launch,
    secs: float,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Classic T-minus thresholds on desktop (test: only T-10m fires)."""
    if not c_assert(secs is not None and secs >= 0, "secs pre-launch"):
        return
    if not c_assert(sent is not None, "sent dict required"):
        return
    is_test = _is_test_launch(L)
    thresholds = take_at_most(list(config.NOTIFY_THRESHOLDS), _MAX_THRESHOLDS)
    for threshold, label in thresholds:  # p10: bounded
        if secs > threshold:
            continue
        key = f"{L.id}:{label}"
        if key in sent:
            continue
        slack = max(threshold * 0.15, 120)
        if is_test and label != "T-10m":
            sent[key] = now.isoformat()
            continue
        if secs < threshold - slack and threshold > 600:
            sent[key] = now.isoformat()
            continue
        # Timeout before next countdown stage when known; else fixed toast length
        expire = expire_ms_until_next_stage(
            L, now, default_ms=_EXPIRE_THRESHOLD_MS
        )
        ignore_result(
            send_desktop(
                f"🚀 Launch {label}",
                _desktop_threshold_body(L, label, now),
                urgency="normal",
                expire_ms=expire,
                url=_stream_url(L),
                enabled=settings.desktop_enabled,
                open_app_on_click=False,
                replace_stage=True,
                transient=True,
            )
        )
        sent[key] = now.isoformat()
        fired.append(key)


def _phone_tags_for(label: str) -> str:
    if not c_assert(isinstance(label, str), "label str"):
        return "rocket"
    tags = {
        "T-24h": "rocket,calendar",
        "T-1h": "rocket,warning",
        "T-10m": "rocket,rotating_light",
    }.get(label, "rocket")
    if not c_assert(isinstance(tags, str) and tags, "tags non-empty"):
        return "rocket"
    return tags


def _notify_phone_thresholds(
    L: Launch,
    secs: float,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Phone pushes: T-24h / T-1h / T-10m (never for test flight)."""
    if not c_assert(settings is not None, "settings required"):
        return
    if not settings.phone_enabled or _is_test_launch(L):
        return
    if not c_assert(secs is not None and secs >= 0, "secs pre-launch"):
        return
    thresholds = take_at_most(list(config.PHONE_NOTIFY_THRESHOLDS), _MAX_THRESHOLDS)
    for threshold, label in thresholds:  # p10: bounded
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
        ok = send_phone(
            ptitle,
            pbody,
            settings=settings,
            click_url=watch,
            tags=_phone_tags_for(label),
            priority=priority,
        )
        if ok:
            sent[phone_key] = now.isoformat()
            fired.append(phone_key)


def _stage_event_key(L: Launch, event: TimelineEvent, is_test: bool) -> str:
    """
    Stable key for stage notifications.
    Test flights must NOT key on live NET — during HOLD we re-pin NET each
    second to freeze T−, which would otherwise re-fire every stage forever.
    """
    if not c_assert(L is not None and event is not None, "stage key args"):
        return "invalid"
    desc = event.description[:40]
    if is_test:
        # Prefer stable scenario cycle id; fall back to hold freeze id / static
        cycle = (getattr(L, "notify_cycle_id", None) or "").strip()
        if not cycle and L.hold_t_minus_sec is not None:
            cycle = f"hold{int(L.hold_t_minus_sec)}"
        if not cycle:
            cycle = "loop"
        return f"{L.id}:stage:{cycle}:{event.relative_sec}:{desc}"
    if not c_assert(event.relative_sec is not None, "relative_sec"):
        return f"{L.id}:stage:0:{desc}"
    return f"{L.id}:stage:{event.relative_sec}:{desc}"


def _notify_stages_for_launch(
    L: Launch,
    secs: float,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Desktop stage events — paused during hold (clock frozen) and scrub."""
    if not c_assert(L is not None and sent is not None, "stage notify args"):
        return
    if not c_assert(settings is not None, "settings required"):
        return
    # Frozen clock — never emit stages while counting is stopped
    if L.is_hold() or L.is_scrub() or L.is_failure():
        return
    abb = (L.status_abbrev or L.status or "").lower()
    if "hold" in abb or "scrub" in abb or "fail" in abb:
        return
    is_test = _is_test_launch(L)
    current_rel = -secs
    events = take_at_most(list(L.stage_events()), MAX_STAGE_EVENTS)
    for event in events:  # p10: bounded
        if current_rel < event.relative_sec:
            continue
        key = _stage_event_key(L, event, is_test)
        if key in sent:
            continue
        overdue = current_rel - event.relative_sec
        max_overdue = 45 if is_test else 180
        if overdue > max_overdue:
            sent[key] = now.isoformat()
            continue
        _notify_stage(L, event, settings, now=now)
        sent[key] = now.isoformat()
        fired.append(key)


def _scrub_notify_key(L: Launch) -> str:
    if not c_assert(L is not None, "launch required"):
        return "scrub:invalid"
    if not c_assert(True is not False, "scrub key"):
        return "scrub:invalid"
    cycle = (getattr(L, "notify_cycle_id", None) or "").strip()
    if not cycle and L.net:
        cycle = L.net.strftime("%Y%m%d%H%M%S")
    if not cycle:
        cycle = "once"
    return f"{L.id}:scrub:{cycle}"


def _mission_body_lines(L: Launch, *extra: str) -> str:
    """Shared body layout matching stage/threshold notifies."""
    if not c_assert(L is not None, "launch required"):
        return ""
    if not c_assert(True is not False, "mission body"):
        return ""
    lines: list[str] = [L.name]
    if L.mission_brief and L.mission_brief.title:
        lines.append(L.mission_brief.title)
    for line in take_at_most(list(extra), _MAX_BODY_LINES):  # p10: bounded
        if line:
            lines.append(line)
    lines.append(f"{L.provider} · {L.pad}, {L.location}".strip(" ·"))
    return "\n".join(take_at_most(lines, _MAX_BODY_LINES))


def _scrub_notify_body(L: Launch, now: datetime, *, failure: bool = False) -> str:
    if not c_assert(L is not None, "launch required"):
        return "Launch scrubbed"
    if not c_assert(now is not None, "now required"):
        return "Launch scrubbed"
    from .models import _fmt_duration

    frozen = L.hold_t_minus_sec
    if frozen is not None:
        t_line = f"Clock stopped at T-{_fmt_duration(float(frozen), precise=True)}"
    else:
        t_line = f"Status · {L.countdown_label(now, precise=True)}"
    headline = "Launch failure" if failure else "Launch scrubbed"
    extras = [headline, t_line]
    if L.hold_reason:
        extras.append(L.hold_reason)
    if L.fail_reason and failure:
        extras.append(L.fail_reason)
    return _mission_body_lines(L, *extras)


def _notify_hold(
    L: Launch,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Desktop notice when countdown goes on hold (emoji style matches stages)."""
    if not c_assert(L is not None and sent is not None, "hold notify args"):
        return
    if not c_assert(isinstance(fired, list), "fired list"):
        return
    if not L.is_hold():
        return
    cycle = (getattr(L, "notify_cycle_id", None) or "").strip()
    if not cycle and L.net:
        cycle = L.net.strftime("%Y%m%d%H%M%S")
    if not cycle:
        cycle = "once"
    key = f"{L.id}:hold:{cycle}"
    if key in sent:
        return
    cd = L.countdown_label(now, precise=True)
    extras = [f"Counting stopped · {cd}"]
    if L.hold_reason:
        extras.append(L.hold_reason)
    ignore_result(
        send_desktop(
            f"🚀 Hold · {cd}",
            _mission_body_lines(L, *extras),
            urgency="normal",
            expire_ms=_EXPIRE_HOLD_MS,
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,
            replace_stage=True,
            transient=True,
        )
    )
    sent[key] = now.isoformat()
    fired.append(key)


def _notify_scrub(
    L: Launch,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """
    Scrub or failure notification: always desktop; phone only for non-test.
    One notify per episode (keyed by notify_cycle_id / NET + kind).
    """
    if not c_assert(L is not None and sent is not None, "scrub notify args"):
        return
    if not c_assert(isinstance(fired, list), "fired list"):
        return
    is_scrub = L.is_scrub()
    is_fail = L.is_failure()
    if not is_scrub and not is_fail:
        return
    kind = "scrub" if is_scrub else "failure"
    key = _scrub_notify_key(L).replace(":scrub:", f":{kind}:")
    if key in sent:
        return
    body = _scrub_notify_body(L, now, failure=is_fail and not is_scrub)
    cd = L.countdown_label(now, precise=True)
    if is_scrub:
        title = f"🚀 Launch scrubbed · {cd}"
    else:
        title = f"🚀 Launch failure · {cd}"
    ignore_result(
        send_desktop(
            title,
            body,
            urgency="normal",
            expire_ms=_EXPIRE_HOLD_MS,
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,
            replace_stage=True,
            transient=True,
        )
    )
    sent[key] = now.isoformat()
    fired.append(key)
    if _is_test_launch(L) or not settings.phone_enabled:
        return
    ok = send_phone(
        title,
        body,
        settings=settings,
        click_url=_stream_url(L),
        tags="rocket,no_entry,warning",
        priority=5,
    )
    if ok:
        phone_key = f"{key}:phone"
        sent[phone_key] = now.isoformat()
        fired.append(phone_key)


def _notify_countdown_resume(
    L: Launch,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """
    Desktop notice when a hold clears and countdown resumes (new/continued NET).
    Tracks prior hold via sent[id:was_hold]; one notify per post-hold NET.
    """
    if not c_assert(L is not None and sent is not None, "resume notify args"):
        return
    if not c_assert(isinstance(fired, list), "fired list"):
        return
    hold_flag = f"{L.id}:was_hold"
    if L.is_hold():
        sent[hold_flag] = now.isoformat()
        return
    if L.is_scrub() or L.is_failure() or not L.is_go():
        return
    if hold_flag not in sent:
        return
    net_s = L.net.isoformat() if L.net else "none"
    key = f"{L.id}:resume:{net_s}"
    if key in sent:
        return
    net_local = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else "TBD"
    cd = L.countdown_label(now, precise=True)
    extras = [
        f"Countdown resumed · {cd}",
        f"NET {net_local}",
    ]
    if L.hold_reason:
        extras.append(L.hold_reason)
    ignore_result(
        send_desktop(
            f"🚀 Countdown resumed · {cd}",
            _mission_body_lines(L, *extras),
            urgency="normal",
            expire_ms=expire_ms_until_next_stage(L, now, default_ms=_EXPIRE_DEFAULT_MS),
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,
            replace_stage=True,
            transient=True,
        )
    )
    sent[key] = now.isoformat()
    try:
        del sent[hold_flag]
    except KeyError:
        pass
    fired.append(key)


def _process_candidate(
    L: Launch,
    now: datetime,
    sent: dict,
    settings: Settings,
    fired: list[str],
) -> None:
    """Run live / threshold / stage notify paths for one launch."""
    if not c_assert(L is not None, "launch required"):
        return
    secs = L.seconds_to_net(now)
    if secs is None:
        return
    if not c_assert(isinstance(sent, dict), "sent must be dict"):
        return
    _notify_webcast_live(L, now, sent, settings, fired)
    _notify_hold(L, now, sent, settings, fired)
    _notify_countdown_resume(L, now, sent, settings, fired)
    _notify_scrub(L, now, sent, settings, fired)
    # Thresholds/stages require a live clock — skip while held/scrubbed/failed
    if L.is_hold() or L.is_scrub() or L.is_failure():
        return
    if secs >= 0:
        _notify_desktop_thresholds(L, secs, now, sent, settings, fired)
        _notify_phone_thresholds(L, secs, now, sent, settings, fired)
    _notify_stages_for_launch(L, secs, now, sent, settings, fired)


def _prune_sent_state(state: dict, sent: dict) -> None:
    """Cap notify state keys to MAX_NOTIFY_KEYS (keep newest)."""
    if not c_assert(isinstance(state, dict) and isinstance(sent, dict), "state types"):
        return
    if len(sent) > MAX_NOTIFY_KEYS:
        items = sorted(sent.items(), key=lambda kv: kv[1], reverse=True)
        state["sent"] = dict(take_at_most(items, MAX_NOTIFY_KEYS))
    else:
        state["sent"] = sent
    if not c_assert("sent" in state, "sent key missing after prune"):
        state["sent"] = {}


def check_and_notify(launches: list[Launch], now: datetime | None = None) -> list[str]:
    """
    Desktop: countdown thresholds + flight stages.
    Phone (ntfy): T-24h, T-1h, T-10m with mission/vehicle/location/T-0/watch.
    """
    now = now or datetime.now(timezone.utc)
    if not c_assert(isinstance(launches, list), "launches must be list"):
        return []
    if not c_assert(now is not None, "now required"):
        return []
    settings = load_settings()
    state = load_notify_state()
    sent: dict = state.setdefault("sent", {})
    fired: list[str] = []

    candidates = _collect_candidates(launches, now)
    for L in take_at_most(candidates, _MAX_CANDIDATES):
        _process_candidate(L, now, sent, settings, fired)

    _prune_sent_state(state, sent)
    save_notify_state(state)
    return take_at_most(fired, MAX_NOTIFY_KEYS)


def test_phone_push() -> bool:
    """Send a sample T-24h-style phone notification."""
    settings = load_settings()
    if not c_assert(settings is not None, "settings required"):
        return False
    if not settings.phone_enabled:
        return False
    if not c_assert(settings.phone_enabled, "phone enabled path"):
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
    if not c_assert(path is not None, "known path missing"):
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data.get("ids")
        if not c_assert(isinstance(ids, list) or ids is None, "ids type"):
            return None
        if isinstance(ids, list):
            return {str(i) for i in take_at_most(ids, MAX_KNOWN_LAUNCH_IDS)}
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return None


def _save_known_ids(ids: set[str]) -> None:
    ensure_dirs()
    if not c_assert(isinstance(ids, set), "ids must be set"):
        return
    capped = take_at_most(sorted(ids), MAX_KNOWN_LAUNCH_IDS)
    if not c_assert(len(capped) <= MAX_KNOWN_LAUNCH_IDS, "ids overflow"):
        return
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ids": capped,
    }
    config.KNOWN_LAUNCHES.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _real_launches(launches: list[Launch]) -> list[Launch]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    out: list[Launch] = []
    for L in take_at_most(launches, MAX_LAUNCHES):
        if L.id and not L.is_test and L.id != config.TEST_FLIGHT_ID:
            out.append(L)
    if not c_assert(len(out) <= MAX_LAUNCHES, "real launches overflow"):
        return take_at_most(out, MAX_LAUNCHES)
    return out


def _new_flight_body(L: Launch) -> tuple[str, str, str]:
    """Return (title, desktop_body, phone_body) for a newly seen flight."""
    if not c_assert(L is not None, "launch required"):
        return "New flight", "", ""
    mission = L.short_name() or L.name
    vehicle = L.vehicle_name()
    net_s = L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else "NET TBD"
    loc = ", ".join(p for p in (L.pad, L.location) if p) or "—"
    core = [
        f"Mission:  {mission}",
        f"Vehicle:  {vehicle}",
        f"Provider: {L.provider or '—'}",
        f"Location: {loc}",
        f"NET:      {net_s}",
        f"Status:   {L.status_abbrev or L.status or '—'}",
    ]
    if not c_assert(len(core) >= 1, "body core empty"):
        return f"New flight added · {mission}", mission, mission
    desktop = "\n".join(take_at_most(core + ["", "Click to open Spaceflight"], _MAX_BODY_LINES))
    phone = "\n".join(take_at_most(core, _MAX_BODY_LINES))
    return f"New flight added · {mission}", desktop, phone


def _notify_one_new_flight(
    L: Launch,
    settings: Settings,
    fired: list[str],
) -> None:
    if not c_assert(L is not None and L.id, "launch with id"):
        return
    if not c_assert(settings is not None, "settings required"):
        return
    title, body, phone_body = _new_flight_body(L)
    ignore_result(
        send_desktop(
            title,
            body,
            urgency="normal",
            expire_ms=20_000,
            url=_stream_url(L),
            enabled=settings.desktop_enabled,
            open_app_on_click=False,
            replace_stage=False,
            transient=True,
        )
    )
    fired.append(f"{L.id}:new_flight:desktop")
    if settings.phone_enabled:
        click = _stream_url(L) or (
            L.mission_brief.page_url if L.mission_brief else None
        )
        ok = send_phone(
            f"New flight: {L.short_name() or L.name}",
            phone_body,
            settings=settings,
            click_url=click,
            tags="rocket,new",
            priority=3,
        )
        if ok:
            fired.append(f"{L.id}:new_flight:phone")
    log.info("New flight notified: %s", L.name)


def _merge_known_ids(known: set[str], current_ids: set[str]) -> set[str]:
    """Remember seen IDs with a hard cap."""
    if not c_assert(isinstance(known, set) and isinstance(current_ids, set), "id sets"):
        return set(current_ids)
    updated = current_ids | known
    if len(updated) > MAX_KNOWN_LAUNCH_IDS:
        known_list = list(known)
        tail = take_at_most(known_list[-400:], 400) if known_list else []
        updated = current_ids | set(tail)
    if not c_assert(len(updated) <= MAX_KNOWN_LAUNCH_IDS + MAX_LAUNCHES, "merge bound"):
        return set(take_at_most(list(updated), MAX_KNOWN_LAUNCH_IDS))
    return updated


def notify_new_flights(launches: list[Launch]) -> list[str]:
    """
    Compare current launch IDs to the last known set.
    On first run, seed the set silently (no flood).
    On later refreshes, notify desktop + phone for each new id.
    """
    if not c_assert(isinstance(launches, list), "launches must be list"):
        return []
    settings = load_settings()
    if not c_assert(settings is not None, "settings required"):
        return []
    real = _real_launches(launches)
    current_ids = {L.id for L in take_at_most(real, MAX_LAUNCHES)}
    known = _load_known_ids()

    if known is None:
        _save_known_ids(current_ids)
        log.info("Seeded known launches (%d) without notifying", len(current_ids))
        return []

    new_ids = current_ids - known
    updated = _merge_known_ids(known, current_ids)
    _save_known_ids(updated)

    if not new_ids:
        return []

    by_id = {L.id: L for L in take_at_most(real, MAX_LAUNCHES)}
    fired: list[str] = []
    for lid in take_at_most(sorted(new_ids), _MAX_NEW_FLIGHTS):
        L = by_id.get(lid)
        if not L:
            continue
        _notify_one_new_flight(L, settings, fired)

    return take_at_most(fired, MAX_NOTIFY_KEYS)
