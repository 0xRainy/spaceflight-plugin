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
from .p10 import MAX_LAUNCHES, c_assert, ignore_result
from .p10.bounds import take_at_most
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
        if not c_assert(hasattr(self, "_stop"), "daemon has _stop"):
            return
        if not c_assert(isinstance(self._stop, bool), "_stop is bool"):
            self._stop = True
            return
        self._stop = True
        append_log("daemon stop signal")

    def run(self) -> int:
        if not c_assert(self.poll_sec >= 0.5, "poll_sec floor"):
            self.poll_sec = 0.5
        if not c_assert(not self._stop, "fresh run must not be stopped"):
            return 1
        write_pid(os_getpid())
        append_log(f"daemon started poll={self.poll_sec}s")
        ignore_result(signal.signal(signal.SIGTERM, self.stop))
        ignore_result(signal.signal(signal.SIGINT, self.stop))

        try:
            while not self._stop:  # p10: nonterminating
                t0 = time.time()
                self.tick()
                # Pace to poll_sec even if tick was slow
                elapsed = time.time() - t0
                remain = self.poll_sec - elapsed
                end = time.time() + max(0.0, remain)
                while not self._stop and time.time() < end:  # p10: bounded
                    time.sleep(min(0.2, max(0.0, end - time.time())))
        finally:
            clear_pid()
            append_log("daemon stopped")
        return 0

    def _emit_from_cache(self) -> list:
        if not c_assert(hasattr(self, "poll_sec"), "daemon initialized"):
            return []
        if not c_assert(MAX_LAUNCHES > 0, "MAX_LAUNCHES positive"):
            return []
        try:
            launches, _ = load_launches()
            launches = take_at_most(launches, MAX_LAUNCHES)
            ignore_result(emit_waybar(refresh=False, launches=launches))
            return launches
        except Exception as exc:  # noqa: BLE001
            append_log(f"waybar emit error: {exc}")
            return []

    def _maybe_net_refresh(self, now_t: float, launches: list | None) -> list | None:
        if not c_assert(isinstance(now_t, (int, float)) and now_t >= 0, "now_t valid"):
            return launches
        if not c_assert(isinstance(self._last_net, (int, float)), "last_net numeric"):
            return launches
        if now_t - self._last_net < config.DAEMON_NET_CHECK_SEC:
            return launches
        try:
            launches, meta = refresh_if_needed(force=False)
            self._last_net = now_t
            launches = take_at_most(launches, MAX_LAUNCHES)
            if meta.get("refreshed"):
                append_log(f"refreshed {len(launches)} launches")
                ignore_result(emit_waybar(refresh=False, launches=launches))
            elif meta.get("refresh_error") and meta.get("skipped_backoff"):
                pass
            elif meta.get("refresh_error"):
                append_log(f"refresh error: {meta['refresh_error']}")
                launches, _ = load_launches()
                launches = take_at_most(launches, MAX_LAUNCHES)
        except Exception as exc:  # noqa: BLE001
            append_log(f"net refresh error: {exc}")
            self._last_net = now_t
        return launches

    def _maybe_notify(self, now_t: float, launches: list) -> None:
        if not c_assert(isinstance(launches, list), "launches list"):
            return
        if not c_assert(isinstance(now_t, (int, float)) and now_t >= 0, "now_t valid"):
            return
        now = datetime.now(timezone.utc)
        hot = False
        for L in launches[:MAX_LAUNCHES]:
            s = L.seconds_to_net(now)
            if s is not None and -7200 <= s <= 7200:
                hot = True
                break
        notify_every = (
            config.DAEMON_NOTIFY_HOT_SEC if hot else config.DAEMON_NOTIFY_IDLE_SEC
        )
        if now_t - self._last_notify < notify_every:
            return
        try:
            fired = check_and_notify(launches)
            self._last_notify = now_t
            if fired:
                append_log(f"notifications: {', '.join(fired[:MAX_LAUNCHES])}")
        except Exception as exc:  # noqa: BLE001
            append_log(f"notify error: {exc}")
            self._last_notify = now_t

    def tick(self) -> None:
        """
        Always rewrite waybar.json first so the bar never freezes if network
        refresh or notifications are slow. No exclusive lock — the daemon is
        the primary continuous writer whether or not the TUI is open.
        """
        if not c_assert(hasattr(self, "_last_net"), "daemon fields present"):
            return
        if not c_assert(self.poll_sec > 0, "poll_sec positive"):
            return
        try:
            now_t = time.time()
            launches: list | None = self._emit_from_cache()
            launches = self._maybe_net_refresh(now_t, launches)
            if launches is None:
                launches, _ = load_launches()
                launches = take_at_most(launches, MAX_LAUNCHES)
            self._maybe_notify(now_t, launches)
        except Exception as exc:  # noqa: BLE001
            append_log(f"tick error: {exc}")
            try:
                ignore_result(emit_waybar(refresh=False))
            except Exception:
                pass


def os_getpid() -> int:
    import os

    if not c_assert(hasattr(os, "getpid"), "os.getpid available"):
        return 0
    pid = os.getpid()
    if not c_assert(isinstance(pid, int) and pid > 0, "pid positive int"):
        return 0
    return pid


def is_running() -> bool:
    pid = read_pid()
    if not c_assert(pid is None or isinstance(pid, int), "pid type"):
        return False
    if pid is None:
        return False
    if not c_assert(pid > 0, "pid positive when present"):
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        clear_pid()
        return False


def main(argv: list[str] | None = None) -> int:
    if not c_assert(argv is None or isinstance(argv, list), "argv list or None"):
        return 2
    if not c_assert(config.DAEMON_POLL_SEC > 0, "default poll positive"):
        return 2
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
