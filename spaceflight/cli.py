"""Command-line entry points for Spaceflight."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import __version__, config
from .api.client import fetch_all, refresh_if_needed
from .cache import load_launches
from .daemon import is_running, main as daemon_main
from .models import Launch
from .notify import check_and_notify
from .waybar import emit_waybar, main as waybar_main


def _print_table(launches: list[Launch], limit: int = 20) -> None:
    now = datetime.now(timezone.utc)
    print(f"{'COUNTDOWN':<14} {'STATUS':<8} {'PROVIDER':<12} {'MISSION'}")
    print("─" * 72)
    for L in launches[:limit]:
        print(
            f"{L.countdown_label(now):<14} "
            f"{(L.status_abbrev or '?')[:8]:<8} "
            f"{(L.provider or '?')[:12]:<12} "
            f"{L.name}"
        )


def cmd_tui(_args: argparse.Namespace) -> int:
    from .tui import run_tui

    return run_tui()


def cmd_refresh(args: argparse.Namespace) -> int:
    try:
        launches = fetch_all(limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"Refresh failed: {exc}", file=sys.stderr)
        return 1
    print(f"Fetched {len(launches)} launches → {config.LAUNCHES_CACHE}")
    emit_waybar(refresh=False)
    _print_table(launches, limit=min(10, args.limit))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    launches, meta = load_launches()
    if not launches or args.refresh:
        launches, meta = refresh_if_needed(force=args.refresh)
    if not args.all:
        now = datetime.now(timezone.utc)
        launches = [L for L in launches if L.is_upcoming(now)]
    age = meta.get("age_sec")
    age_s = f"{int(age)}s" if age is not None else "?"
    print(f"# {len(launches)} launches  cache_age={age_s}  source={meta.get('source')}")
    if args.json:
        print(json.dumps([L.to_dict() for L in launches[: args.limit]], indent=2, default=str))
    else:
        _print_table(launches, limit=args.limit)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    launches, _ = load_launches()
    if not launches:
        launches, _ = refresh_if_needed(force=True)
    q = (args.query or "").lower()
    match = None
    for L in launches:
        if q in L.id.lower() or q in L.name.lower() or q in L.slug.lower():
            match = L
            break
    if not match and launches and not q:
        match = launches[0]
    if not match:
        print("No match", file=sys.stderr)
        return 1
    L = match
    now = datetime.now(timezone.utc)
    print(L.name)
    print(f"  {L.countdown_label(now)}  ·  {L.status}")
    if L.net:
        print(f"  NET  {L.net.isoformat()}  ({L.net.astimezone().strftime('%Y-%m-%d %H:%M %Z')})")
    print(f"  Provider  {L.provider}")
    print(f"  Pad       {L.pad}, {L.location}")
    print(f"  Vehicle   {L.vehicle.full_name or L.vehicle.name}")
    print(f"  Mission   {L.payload.name}  [{L.payload.type}]  {L.payload.orbit}")
    if L.payload.description:
        print()
        print(L.payload.description)
    if L.streams:
        print()
        print("Streams:")
        for s in L.streams:
            print(f"  · {s.title}: {s.url}")
    if L.updates:
        print()
        print("Updates:")
        for u in L.updates[:8]:
            when = u.created_on.isoformat() if u.created_on else ""
            print(f"  · [{when}] {u.comment}")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    # Rebuild argv for daemon parser
    argv = []
    if args.once:
        argv.append("--once")
    if args.status:
        argv.append("--status")
    if args.poll is not None:
        argv.extend(["--poll", str(args.poll)])
    return daemon_main(argv)


def cmd_waybar(args: argparse.Namespace) -> int:
    argv = ["--refresh"] if args.refresh else []
    return waybar_main(argv)


def cmd_notify_test(args: argparse.Namespace) -> int:
    from .notify import send_desktop, test_phone_push, _phone_t24h_body
    from .settings import load_settings, write_default_config

    settings = load_settings()
    write_default_config()

    if getattr(args, "phone", False):
        if not settings.phone_enabled:
            print("Phone push not configured.")
            print(f"  1. Install ntfy on your phone: https://ntfy.sh")
            print(f"  2. Edit {config.CONFIG_DIR / 'config.toml'}")
            print(f'     set phone.ntfy_topic = "your-secret-topic-name"')
            print(f"  3. Subscribe to that topic in the app")
            print(f"  Or: export SPACEFLIGHT_NTFY_TOPIC=your-secret-topic-name")
            return 1
        ok = test_phone_push()
        print("Phone push sent" if ok else "Phone push failed (check topic/server)")
        return 0 if ok else 1

    launches, _ = load_launches()
    if not launches:
        launches, _ = refresh_if_needed(force=True)
    L = None
    now = datetime.now(timezone.utc)
    for cand in launches:
        if cand.is_upcoming(now):
            L = cand
            break
    L = L or (launches[0] if launches else None)
    if not L:
        print("No launches")
        return 1
    stream = L.primary_stream()
    send_desktop(
        "🚀 Spaceflight desktop test",
        f"{L.name}\n{L.countdown_label()}\n{L.provider} · {L.location}",
        urgency="normal",
        url=stream.url if stream else None,
        enabled=True,
    )
    print("Sent desktop notification")
    # Preview what the phone T-24h message would look like
    title, body, watch = _phone_t24h_body(L)
    print("\n— Phone T-24h preview —")
    print(title)
    print(body)
    if settings.phone_enabled:
        print(f"\nntfy topic configured: {settings.ntfy_topic[:8]}…@{settings.ntfy_server}")
        print("Run: spaceflight notify-test --phone")
    else:
        print(f"\nPhone not configured. See {config.CONFIG_DIR / 'config.example.toml'}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    from .settings import load_settings

    launches, meta = load_launches()
    settings = load_settings()
    print(f"version:    {__version__}")
    print(f"cache:      {config.LAUNCHES_CACHE}")
    print(f"launches:   {len(launches)}")
    print(f"cache_age:  {meta.get('age_sec')}")
    print(f"daemon:     {'running' if is_running() else 'stopped'}")
    print(f"log:        {config.LOG_FILE}")
    print(f"waybar:     {config.WAYBAR_CACHE}")
    print(f"desktop:    {'on' if settings.desktop_enabled else 'off'}")
    if settings.phone_enabled:
        print(f"phone:      ntfy topic set → {settings.ntfy_server}")
    else:
        print(f"phone:      not configured ({config.CONFIG_DIR / 'config.toml'})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spaceflight",
        description="Terminal rocket launch tracker (btop-style TUI + waybar + notifications)",
    )
    p.add_argument("--version", action="version", version=f"spaceflight {__version__}")
    sub = p.add_subparsers(dest="command")

    # default: tui
    tui_p = sub.add_parser("tui", help="Open interactive TUI (default)")
    tui_p.set_defaults(func=cmd_tui)

    r = sub.add_parser("refresh", help="Fetch latest launch data")
    r.add_argument("--limit", type=int, default=config.DEFAULT_FETCH_LIMIT)
    r.set_defaults(func=cmd_refresh)

    ls = sub.add_parser("list", help="List cached/upcoming launches")
    ls.add_argument("--limit", type=int, default=20)
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--refresh", action="store_true")
    ls.add_argument("--all", action="store_true", help="Include recently completed flights")
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="Show details for a launch (name/id substring)")
    sh.add_argument("query", nargs="?", default="")
    sh.set_defaults(func=cmd_show)

    d = sub.add_parser("daemon", help="Background refresh + notifications")
    d.add_argument("--once", action="store_true")
    d.add_argument("--status", action="store_true")
    d.add_argument("--poll", type=float, default=None)
    d.set_defaults(func=cmd_daemon)

    w = sub.add_parser("waybar", help="Print waybar JSON module output")
    w.add_argument("--refresh", action="store_true")
    w.set_defaults(func=cmd_waybar)

    n = sub.add_parser("notify-test", help="Test desktop and/or phone (ntfy) notifications")
    n.add_argument("--phone", action="store_true", help="Send a test push to your phone via ntfy")
    n.set_defaults(func=cmd_notify_test)

    st = sub.add_parser("status", help="Show paths and daemon state")
    st.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Default to TUI when no command
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        if not argv or argv[0] not in {
            "tui",
            "refresh",
            "list",
            "show",
            "daemon",
            "waybar",
            "notify-test",
            "status",
        }:
            if argv and argv[0] in ("-h", "--help", "--version"):
                pass
            elif not argv:
                argv = ["tui"]
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["tui"])
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
