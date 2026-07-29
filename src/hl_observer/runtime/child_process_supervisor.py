"""Bounded supervision for long-lived, read-only helper processes."""

from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


@dataclass(frozen=True, slots=True)
class ChildProcessStatus:
    state: str
    pid: int | None
    restart_count: int
    last_exit_code: int | None
    last_checked_at_ms: int
    log_path: str
    reason: str


class ChildProcessSupervisor:
    """Keep one helper alive without an unbounded restart loop.

    The child receives a bounded, persistent log instead of ``DEVNULL``. Log
    rotation happens before each spawn, when no child owns the file.
    """

    def __init__(
        self,
        *,
        name: str,
        argv: list[str],
        cwd: Path,
        log_path: Path,
        spawn: Callable[[list[str], TextIO], Any],
        now_ms: Callable[[], int] | None = None,
        announce: Callable[[str], None] | None = None,
        max_restarts: int = 5,
        restart_window_ms: int = 300_000,
        max_log_bytes: int = 5_000_000,
        log_backups: int = 3,
    ) -> None:
        self.name = str(name)
        self.argv = list(argv)
        self.cwd = Path(cwd)
        self.log_path = Path(log_path)
        self._spawn = spawn
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._announce = announce or (lambda _message: None)
        self.max_restarts = max(0, int(max_restarts))
        self.restart_window_ms = max(1, int(restart_window_ms))
        self.max_log_bytes = max(1, int(max_log_bytes))
        self.log_backups = max(0, int(log_backups))
        self.process: Any | None = None
        self._log_handle: TextIO | None = None
        self._restart_times: deque[int] = deque()
        self.restart_count = 0
        self.last_exit_code: int | None = None
        self.last_checked_at_ms = 0

    def start(self, *, reason: str = "initial_start") -> ChildProcessStatus:
        now = self._now_ms()
        self.last_checked_at_ms = now
        if self._is_alive():
            return self.status(reason="already_alive")
        self._close_log()
        if reason != "initial_start" and not self._restart_allowed(now):
            self._announce(
                f"{self.name}: restart refuse, budget "
                f"{self.max_restarts}/{self.restart_window_ms}ms atteint"
            )
            return self.status(state="RESTART_BUDGET_EXHAUSTED", reason="restart_budget")
        self._rotate_log_if_needed()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open(
            "a",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        try:
            self.process = self._spawn(self.argv, self._log_handle)
        except Exception:
            self._close_log()
            self.process = None
            raise
        if reason != "initial_start":
            self.restart_count += 1
            self._restart_times.append(now)
        if reason == "initial_start":
            self.last_exit_code = None
        self._announce(
            f"{self.name}: {reason} pid={getattr(self.process, 'pid', None)} "
            f"log={self.log_path}"
        )
        return self.status(state="RUNNING", reason=reason)

    def check_and_recover(self) -> ChildProcessStatus:
        now = self._now_ms()
        self.last_checked_at_ms = now
        if self.process is None:
            return self.start(reason="missing_process")
        exit_code = self._poll()
        if exit_code is None:
            return self.status(state="RUNNING", reason="process_alive")
        self.last_exit_code = int(exit_code)
        self._announce(f"{self.name}: mort detectee exit_code={exit_code}")
        self.process = None
        self._close_log()
        return self.start(reason=f"restart_after_exit_{exit_code}")

    def stop(self) -> ChildProcessStatus:
        now = self._now_ms()
        self.last_checked_at_ms = now
        proc = self.process
        if proc is not None and self._poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        self.process = None
        self._close_log()
        return self.status(state="STOPPED", reason="requested_stop")

    def status(
        self,
        *,
        state: str | None = None,
        reason: str = "",
    ) -> ChildProcessStatus:
        alive = self._is_alive()
        resolved_state = state or ("RUNNING" if alive else "STOPPED")
        return ChildProcessStatus(
            state=resolved_state,
            pid=int(getattr(self.process, "pid", 0) or 0) or None,
            restart_count=self.restart_count,
            last_exit_code=self.last_exit_code,
            last_checked_at_ms=self.last_checked_at_ms,
            log_path=str(self.log_path),
            reason=reason,
        )

    def _poll(self) -> int | None:
        if self.process is None:
            return 0
        poll = getattr(self.process, "poll", None)
        if callable(poll):
            return poll()
        return None

    def _is_alive(self) -> bool:
        return self.process is not None and self._poll() is None

    def _restart_allowed(self, now: int) -> bool:
        cutoff = now - self.restart_window_ms
        while self._restart_times and self._restart_times[0] < cutoff:
            self._restart_times.popleft()
        return len(self._restart_times) < self.max_restarts

    def _close_log(self) -> None:
        if self._log_handle is None:
            return
        with suppress(Exception):
            self._log_handle.flush()
            os.fsync(self._log_handle.fileno())
        with suppress(Exception):
            self._log_handle.close()
        self._log_handle = None

    def _rotate_log_if_needed(self) -> None:
        try:
            if not self.log_path.exists() or self.log_path.stat().st_size <= self.max_log_bytes:
                return
            for index in range(self.log_backups, 0, -1):
                source = self.log_path.with_suffix(self.log_path.suffix + f".{index}")
                if not source.exists():
                    continue
                if index >= self.log_backups:
                    source.unlink()
                else:
                    source.replace(
                        self.log_path.with_suffix(self.log_path.suffix + f".{index + 1}")
                    )
            if self.log_backups > 0:
                self.log_path.replace(self.log_path.with_suffix(self.log_path.suffix + ".1"))
            else:
                self.log_path.unlink()
        except OSError as exc:
            self._announce(f"{self.name}: rotation log impossible: {exc}")


__all__ = ["ChildProcessStatus", "ChildProcessSupervisor"]
