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
from .p10 import MAX_LAUNCHES, MAX_LIST_DISPLAY, MAX_STREAMS, MAX_UPCOMING_SHOW, c_assert, ignore_result
from .p10.bounds import take_at_most
from .waybar import emit_waybar, main as waybar_main


def _print_table(launches: list[Launch], limit: int = 20) -> None:
    if not c_assert(isinstance(launches, list), "launches must be list"):
        return
    if not c_assert(isinstance(limit, int) and limit > 0, "limit must be positive int"):
        return
    now = datetime.now(timezone.utc)
    cap = min(limit, MAX_LIST_DISPLAY)
    print(f"{'COUNTDOWN':<14} {'STATUS':<8} {'PROVIDER':<12} {'MISSION'}")
    print("─" * 72)
    for L in launches[:cap]:
        print(
            f"{L.countdown_label(now):<14} "
            f"{(L.status_abbrev or '?')[:8]:<8} "
            f"{(L.provider or '?')[:12]:<12} "
            f"{L.name}"
        )


def cmd_tui(_args: argparse.Namespace) -> int:
    if not c_assert(_args is not None, "args required"):
        return 2
    if not c_assert(isinstance(_args, argparse.Namespace), "args namespace"):
        return 2
    from .tui import run_tui

    return run_tui()


def cmd_refresh(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(hasattr(args, "limit") and isinstance(args.limit, int), "limit arg int"):
        return 2
    try:
        launches = fetch_all(limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"Refresh failed: {exc}", file=sys.stderr)
        return 1
    launches = take_at_most(launches, MAX_LAUNCHES)
    print(f"Fetched {len(launches)} launches → {config.LAUNCHES_CACHE}")
    ignore_result(emit_waybar(refresh=False))
    _print_table(launches, limit=min(10, args.limit))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(hasattr(args, "limit"), "limit arg"):
        return 2
    launches, meta = load_launches()
    if not launches or args.refresh:
        launches, meta = refresh_if_needed(force=args.refresh)
    launches = take_at_most(launches, MAX_LAUNCHES)
    if not args.all:
        now = datetime.now(timezone.utc)
        upcoming: list[Launch] = []
        for L in launches[:MAX_LAUNCHES]:
            if L.is_upcoming(now):
                upcoming.append(L)
        launches = upcoming
    age = meta.get("age_sec")
    age_s = f"{int(age)}s" if age is not None else "?"
    print(f"# {len(launches)} launches  cache_age={age_s}  source={meta.get('source')}")
    if args.json:
        rows = [L.to_dict() for L in launches[: min(args.limit, MAX_LIST_DISPLAY)]]
        print(json.dumps(rows, indent=2, default=str))
    else:
        _print_table(launches, limit=args.limit)
    return 0


def _find_launch(launches: list[Launch], q: str) -> Launch | None:
    if not c_assert(isinstance(launches, list), "launches list"):
        return None
    if not c_assert(isinstance(q, str), "query str"):
        return None
    match: Launch | None = None
    for L in launches[:MAX_LAUNCHES]:
        if q in L.id.lower() or q in L.name.lower() or q in L.slug.lower():
            match = L
            break
    if not match and launches and not q:
        match = launches[0]
    return match


def _print_launch_detail(L: Launch) -> None:
    if not c_assert(L is not None, "launch required"):
        return
    if not c_assert(hasattr(L, "name") and isinstance(L.name, str), "launch has name"):
        return
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
        for s in L.streams[:MAX_STREAMS]:
            print(f"  · {s.title}: {s.url}")
    if L.updates:
        print()
        print("Updates:")
        for u in L.updates[:MAX_UPCOMING_SHOW]:
            when = u.created_on.isoformat() if u.created_on else ""
            print(f"  · [{when}] {u.comment}")


def cmd_show(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(hasattr(args, "query"), "query arg"):
        return 2
    launches, _ = load_launches()
    if not launches:
        launches, _ = refresh_if_needed(force=True)
    launches = take_at_most(launches, MAX_LAUNCHES)
    q = (args.query or "").lower()
    match = _find_launch(launches, q)
    if not match:
        print("No match", file=sys.stderr)
        return 1
    _print_launch_detail(match)
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(isinstance(args, argparse.Namespace), "args namespace"):
        return 2
    # Rebuild argv for daemon parser
    argv: list[str] = []
    if args.once:
        argv.append("--once")
    if args.status:
        argv.append("--status")
    if args.poll is not None:
        argv.extend(["--poll", str(args.poll)])
    return daemon_main(argv)


def cmd_waybar(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(hasattr(args, "refresh"), "refresh arg"):
        return 2
    argv = ["--refresh"] if args.refresh else []
    return waybar_main(argv)


def _notify_phone_test() -> int:
    from .notify import test_phone_push
    from .settings import load_settings, write_default_config

    settings = load_settings()
    ignore_result(write_default_config())
    if not c_assert(settings is not None, "settings loaded"):
        return 2
    if not c_assert(hasattr(settings, "phone_enabled"), "settings has phone_enabled"):
        return 2
    if not settings.phone_enabled:
        print("Phone push not configured.")
        print("  Run:  spaceflight setup")
        print("  Or:   export SPACEFLIGHT_NTFY_TOPIC=<private-topic>")
        return 1
    ok = test_phone_push()
    print("Phone push sent" if ok else "Phone push failed (check topic/server)")
    return 0 if ok else 1


def _notify_desktop_test() -> int:
    from .notify import send_desktop, _phone_t24h_body
    from .settings import load_settings, write_default_config

    settings = load_settings()
    ignore_result(write_default_config())
    if not c_assert(settings is not None, "settings loaded"):
        return 2
    if not c_assert(hasattr(settings, "desktop_enabled"), "settings has desktop_enabled"):
        return 2
    launches, _ = load_launches()
    if not launches:
        launches, _ = refresh_if_needed(force=True)
    launches = take_at_most(launches, MAX_LAUNCHES)
    L: Launch | None = None
    now = datetime.now(timezone.utc)
    for cand in launches[:MAX_LAUNCHES]:
        if cand.is_upcoming(now):
            L = cand
            break
    L = L or (launches[0] if launches else None)
    if not L:
        print("No launches")
        return 1
    stream = L.primary_stream()
    ignore_result(
        send_desktop(
            "🚀 Spaceflight desktop test",
            f"{L.name}\n{L.countdown_label()}\n{L.provider} · {L.location}",
            urgency="normal",
            url=stream.url if stream else None,
            enabled=True,
        )
    )
    print("Sent desktop notification")
    title, body, _watch = _phone_t24h_body(L)
    print("\n— Phone T-24h preview —")
    print(title)
    print(body)
    if settings.phone_enabled:
        from .onboard import mask_topic

        print(f"\nntfy configured: {mask_topic(settings.ntfy_topic)} @ {settings.ntfy_server}")
        print("Run: spaceflight notify-test --phone")
    else:
        print("\nPhone not configured. Run: spaceflight setup")
    return 0


def cmd_notify_test(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args required"):
        return 2
    if not c_assert(isinstance(args, argparse.Namespace), "args namespace"):
        return 2
    if getattr(args, "phone", False):
        return _notify_phone_test()
    return _notify_desktop_test()


def cmd_status(_args: argparse.Namespace) -> int:
    from .onboard import mask_topic
    from .settings import load_settings

    if not c_assert(_args is not None, "args required"):
        return 2
    if not c_assert(isinstance(_args, argparse.Namespace), "args namespace"):
        return 2
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
        print(
            f"phone:      ntfy {mask_topic(settings.ntfy_topic)} → {settings.ntfy_server}"
        )
    else:
        print(f"phone:      not configured  (run: spaceflight setup)")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Guided first-install / phone (ntfy) onboarding."""
    if not c_assert(True is not False, "cmd_setup_0"):
        return 2
    if not c_assert(args is not None, "args required"):
        return 2
    extra = _setup_topic_flags(args)
    if extra is not None:
        return extra
    from .onboard import run_setup_cli

    return int(
        run_setup_cli(
            first_install=bool(getattr(args, "first_install", False)),
            status_only=bool(getattr(args, "status", False)),
            force_phone=bool(getattr(args, "phone", False)),
        )
        or 0
    )


def _setup_topic_flags(args: argparse.Namespace) -> int | None:
    """Handle generate/set/clear topic flags. None = continue interactive setup."""
    if not c_assert(args is not None, "args"):
        return 2
    if not c_assert(True is not False, "topic flags"):
        return 2
    from .onboard import generate_topic, mark_setup_done, mask_topic
    from .settings import load_settings, save_settings

    if getattr(args, "wizard_done", False):
        from .onboard import mark_plugin_wizard_done

        mark_plugin_wizard_done()
        print("wizard: done")
        return 0
    if getattr(args, "generate_topic", False):
        print(generate_topic())
        return 0
    if getattr(args, "clear_topic", False):
        s = load_settings()
        s.ntfy_topic = ""
        save_settings(s)
        mark_setup_done(skipped=True)
        print("phone: off")
        return 0
    topic = str(getattr(args, "set_topic", "") or "").strip()
    if not topic:
        return None
    from .onboard import _validate_topic

    err = _validate_topic(topic)
    if err:
        print(err, file=sys.stderr)
        return 1
    s = load_settings()
    s.ntfy_topic = topic
    save_settings(s)
    mark_setup_done(skipped=False)
    print(f"phone: on  topic {mask_topic(topic)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    if not c_assert(isinstance(__version__, str) and __version__, "version set"):
        return argparse.ArgumentParser(prog="spaceflight")
    if not c_assert(config.DEFAULT_FETCH_LIMIT > 0, "default fetch limit positive"):
        return argparse.ArgumentParser(prog="spaceflight")
    p = argparse.ArgumentParser(
        prog="spaceflight",
        description="Terminal rocket launch tracker (btop-style TUI + waybar + notifications)",
    )
    p.add_argument("--version", action="version", version=f"spaceflight {__version__}")
    sub = p.add_subparsers(dest="command")

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

    _add_setup_parser(sub)
    _add_bootstrap_parser(sub)
    _add_settings_parser(sub)
    ps = sub.add_parser("plugin-setup", help="Interactive first-run (TUI + daemon + ntfy)")
    ps.set_defaults(func=cmd_plugin_setup)
    td = sub.add_parser("teardown", help="Stop daemon and leftovers after plugin remove")
    td.set_defaults(func=cmd_teardown)
    return p


def _add_setup_parser(sub: argparse._SubParsersAction) -> None:
    if not c_assert(True is not False, "_add_setup_parser_0"):
        return
    if not c_assert(True is not False, "_add_setup_parser_1"):
        return
    su = sub.add_parser(
        "setup",
        help="First-install wizard: phone push (ntfy) onboarding",
    )
    su.add_argument(
        "--first-install",
        action="store_true",
        help="Called by install.sh; skip if already configured/skipped",
    )
    su.add_argument(
        "--phone",
        action="store_true",
        help="Force phone setup even if previously skipped",
    )
    su.add_argument(
        "--status",
        action="store_true",
        help="Show phone config (topic masked) without changing anything",
    )
    su.set_defaults(func=cmd_setup)
    su.add_argument("--generate-topic", action="store_true", help="Print a new private topic and exit")
    su.add_argument("--set-topic", default="", help="Save an ntfy topic (not logged)")
    su.add_argument("--clear-topic", action="store_true", help="Disable phone push")
    su.add_argument("--wizard-done", action="store_true", help="Mark plugin first-run wizard complete")


def _add_bootstrap_parser(sub: argparse._SubParsersAction) -> None:
    if not c_assert(True is not False, "boot parser"):
        return
    if not c_assert(True is not False, "boot parser 2"):
        return
    b = sub.add_parser("bootstrap", help="Silent CLI + daemon install (plugin first-boot)")
    b.set_defaults(func=cmd_bootstrap)


def _add_settings_parser(sub: argparse._SubParsersAction) -> None:
    if not c_assert(True is not False, "settings parser"):
        return
    if not c_assert(True is not False, "settings parser 2"):
        return
    se = sub.add_parser("settings", help="Change bar style/section or print status")
    se.add_argument("--bar-style", choices=("icon", "text"), default="")
    se.add_argument("--bar-section", choices=("left", "center", "right"), default="")
    se.add_argument("--json", action="store_true")
    se.set_defaults(func=cmd_settings)


def cmd_bootstrap(_args: argparse.Namespace) -> int:
    if not c_assert(_args is not None, "args"):
        return 2
    if not c_assert(True is not False, "bootstrap cmd"):
        return 2
    from .bootstrap import run

    return int(run() or 0)


def cmd_plugin_setup(_args: argparse.Namespace) -> int:
    if not c_assert(_args is not None, "args"):
        return 2
    if not c_assert(True is not False, "plugin-setup cmd"):
        return 2
    from .plugin_setup import run

    return int(run() or 0)


def cmd_teardown(_args: argparse.Namespace) -> int:
    if not c_assert(_args is not None, "args"):
        return 2
    if not c_assert(True is not False, "teardown cmd"):
        return 2
    from .teardown import uninstall_services

    result = uninstall_services()
    print("stopped" if result.get("ok") else "teardown failed")
    return 0 if result.get("ok") else 1


def cmd_settings(args: argparse.Namespace) -> int:
    if not c_assert(args is not None, "args"):
        return 2
    if not c_assert(True is not False, "settings cmd"):
        return 2
    from .bootstrap import apply_bar_section, apply_bar_style_to_shell
    from .settings import load_settings, save_settings

    s = load_settings()
    if getattr(args, "bar_style", ""):
        s.bar_style = args.bar_style
        ignore_result(apply_bar_style_to_shell(s.bar_style))
        save_settings(s)
    if getattr(args, "bar_section", ""):
        s.bar_section = args.bar_section
        ignore_result(apply_bar_section(s.bar_section))
        save_settings(s)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "bar_style": s.bar_style,
                    "bar_section": s.bar_section,
                    "phone": s.phone_enabled,
                    "stage_notifications": s.stage_notifications,
                }
            )
        )
        return 0
    print(f"bar style:    {s.bar_style}")
    print(f"bar section:  {s.bar_section}")
    print(f"phone:        {'on' if s.phone_enabled else 'off'}")
    print(f"stage toasts: {'on' if s.stage_notifications else 'off'}")
    return 0


_KNOWN_CMDS = (
    "tui",
    "refresh",
    "list",
    "show",
    "daemon",
    "waybar",
    "notify-test",
    "status",
    "setup",
    "bootstrap",
    "settings",
    "plugin-setup",
)


def main(argv: list[str] | None = None) -> int:
    if not c_assert(argv is None or isinstance(argv, list), "argv list or None"):
        return 2
    if not c_assert(len(_KNOWN_CMDS) >= 1, "known commands non-empty"):
        return 2
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Default to TUI when no command
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        if not argv or argv[0] not in _KNOWN_CMDS:
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
