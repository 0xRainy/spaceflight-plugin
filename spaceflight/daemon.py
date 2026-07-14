"""Background service: refresh data, update waybar cache, send notifications."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from . import config
from .api.client import refresh_if_needed
from .cache import append_log, clear_pid, load_launches, read_pid, write_pid
from .notify import check_and_notify
from .waybar import emit_waybar


class Daemon:
    def __init__(self, poll_sec: float = config.DAEMON_POLL_SEC) -> None:
        # poll_sec: how often we recompute countdowns/notifications (cheap).
        # Network refresh is separately gated to MIN_FETCH_INTERVAL_SEC (5 min).
        self.poll_sec = poll_sec
        self._stop = False

    def stop(self, *_args) -> None:
        self._stop = True
        append_log("daemon stop signal")

    def run(self) -> int:
        write_pid(os_getpid())
        append_log("daemon started")
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        try:
            while not self._stop:
                self.tick()
                # Sleep in small slices so SIGTERM is responsive
                end = time.time() + self.poll_sec
                while not self._stop and time.time() < end:
                    time.sleep(min(1.0, end - time.time()))
        finally:
            clear_pid()
            append_log("daemon stopped")
        return 0

    def tick(self) -> None:
        try:
            launches, meta = refresh_if_needed(force=False)
            if meta.get("refreshed"):
                append_log(f"refreshed {len(launches)} launches")
            elif meta.get("refresh_error"):
                append_log(f"refresh error: {meta['refresh_error']}")
                launches, _ = load_launches()

            fired = check_and_notify(launches)
            if fired:
                append_log(f"notifications: {', '.join(fired)}")

            emit_waybar(refresh=False)
        except Exception as exc:  # noqa: BLE001
            append_log(f"tick error: {exc}")


def os_getpid() -> int:
    import os

    return os.getpid()


def is_running() -> bool:
    pid = read_pid()
    if pid is None:
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        clear_pid()
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spaceflight-daemon")
    parser.add_argument("--poll", type=float, default=config.DAEMON_POLL_SEC, help="Poll interval seconds")
    parser.add_argument("--once", action="store_true", help="Single tick then exit")
    parser.add_argument("--status", action="store_true", help="Print daemon status")
    args = parser.parse_args(argv)

    if args.status:
        pid = read_pid()
        running = is_running()
        print(f"running={running} pid={pid}")
        print(f"log={config.LOG_FILE}")
        print(f"cache={config.LAUNCHES_CACHE}")
        return 0

    if args.once:
        Daemon(poll_sec=args.poll).tick()
        return 0

    if is_running():
        print(f"Already running (pid {read_pid()})", file=sys.stderr)
        return 1

    return Daemon(poll_sec=args.poll).run()
