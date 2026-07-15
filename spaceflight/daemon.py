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
        # poll_sec: how often we rewrite waybar.json (must be ~1s for live countdowns).
        # Network refresh stays gated to MIN_FETCH_INTERVAL_SEC.
        self.poll_sec = max(0.5, float(poll_sec))
        self._stop = False
        self._last_notify = 0.0
        self._last_net = 0.0

    def stop(self, *_args) -> None:
        self._stop = True
        append_log("daemon stop signal")

    def run(self) -> int:
        write_pid(os_getpid())
        append_log(f"daemon started poll={self.poll_sec}s")
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        try:
            while not self._stop:
                t0 = time.time()
                self.tick()
                # Pace to poll_sec even if tick was slow
                elapsed = time.time() - t0
                remain = self.poll_sec - elapsed
                end = time.time() + max(0.0, remain)
                while not self._stop and time.time() < end:
                    time.sleep(min(0.2, end - time.time()))
        finally:
            clear_pid()
            append_log("daemon stopped")
        return 0

    def tick(self) -> None:
        try:
            now_t = time.time()

            # Network refresh attempt (still rate-limited / backoff inside client)
            if now_t - self._last_net >= config.DAEMON_NET_CHECK_SEC:
                launches, meta = refresh_if_needed(force=False)
                self._last_net = now_t
                if meta.get("refreshed"):
                    append_log(f"refreshed {len(launches)} launches")
                elif meta.get("refresh_error") and meta.get("skipped_backoff"):
                    # Quiet cooldown — log at most via existing path occasionally
                    pass
                elif meta.get("refresh_error"):
                    append_log(f"refresh error: {meta['refresh_error']}")
                    launches, _ = load_launches()
            else:
                launches, _ = load_launches()

            now = datetime.now(timezone.utc)
            hot = any(
                (s := L.seconds_to_net(now)) is not None and -7200 <= s <= 7200
                for L in launches
            )
            notify_every = (
                config.DAEMON_NOTIFY_HOT_SEC if hot else config.DAEMON_NOTIFY_IDLE_SEC
            )
            if now_t - self._last_notify >= notify_every:
                fired = check_and_notify(launches)
                self._last_notify = now_t
                if fired:
                    append_log(f"notifications: {', '.join(fired)}")

            # Always rewrite waybar JSON so cat-based module ticks every second
            emit_waybar(refresh=False)
        except Exception as exc:  # noqa: BLE001
            append_log(f"tick error: {exc}")
            try:
                # Still try to keep the bar alive on errors
                emit_waybar(refresh=False)
            except Exception:
                pass


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
    parser.add_argument(
        "--poll",
        type=float,
        default=config.DAEMON_POLL_SEC,
        help="Waybar rewrite interval seconds (default 1)",
    )
    parser.add_argument("--once", action="store_true", help="Single tick then exit")
    parser.add_argument("--status", action="store_true", help="Print daemon status")
    args = parser.parse_args(argv)

    if args.status:
        pid = read_pid()
        running = is_running()
        print(f"running={running} pid={pid}")
        print(f"poll={config.DAEMON_POLL_SEC}s")
        print(f"log={config.LOG_FILE}")
        print(f"cache={config.LAUNCHES_CACHE}")
        print(f"waybar={config.WAYBAR_CACHE}")
        return 0

    if args.once:
        Daemon(poll_sec=args.poll).tick()
        return 0

    if is_running():
        print(f"Already running (pid {read_pid()})", file=sys.stderr)
        return 1

    return Daemon(poll_sec=args.poll).run()
