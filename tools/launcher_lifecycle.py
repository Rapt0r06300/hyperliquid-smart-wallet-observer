"""Bounded lifecycle guard for Windows command launchers.

The root ``.cmd`` files deliberately start long-lived children in the
background.  Closing a console window bypasses batch labels such as
``:cleanup`` and therefore used to leave those children behind.  This module
does not search by a global process name: it records only descendants created
after the launcher started, verifies their command line, and then performs a
graceful, bounded stop when the owning launcher disappears.

The helper is PAPER/read-only with respect to the economic system.  Its only
write is an optional control flag explicitly supplied by the launcher and an
append-only lifecycle log under ``runtime/logs``.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


_POLL_S = 0.75
_GRACE_S = 8.0
_EXCLUDED_MARKERS = (
    "claudecode-official-max",
    "\\.codex\\",
    "/.codex/",
    "salad",
)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    parent_pid: int
    name: str
    commandline: str
    created_at: float | None = None


def parse_snapshot(payload: str) -> dict[int, ProcessInfo]:
    """Parse the compact PowerShell JSON snapshot without trusting its shape."""
    if not payload.strip():
        return {}
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    records = raw if isinstance(raw, list) else [raw]
    result: dict[int, ProcessInfo] = {}
    for item in records:
        if not isinstance(item, Mapping):
            continue
        try:
            pid = int(item.get("ProcessId"))
            parent_pid = int(item.get("ParentProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        created_raw = item.get("CreatedAt")
        try:
            created_at = float(created_raw) if created_raw not in (None, "") else None
            # Win32 FILETIME is 100 ns ticks since 1601; normalize to Unix
            # seconds so it can be compared with time.time().
            if created_at is not None and created_at > 10**12:
                created_at = (created_at - 116444736000000000) / 10_000_000
        except (TypeError, ValueError):
            created_at = None
        result[pid] = ProcessInfo(
            pid=pid,
            parent_pid=parent_pid,
            name=str(item.get("Name") or ""),
            commandline=str(item.get("CommandLine") or ""),
            created_at=created_at,
        )
    return result


def descendant_pids(snapshot: Mapping[int, ProcessInfo], root_pid: int) -> set[int]:
    """Return the complete descendant set, including grandchildren and workers."""
    children: dict[int, list[int]] = {}
    for info in snapshot.values():
        children.setdefault(info.parent_pid, []).append(info.pid)
    found: set[int] = set()
    frontier = [int(root_pid)]
    while frontier:
        parent = frontier.pop()
        for child in children.get(parent, []):
            if child in found or child == root_pid:
                continue
            found.add(child)
            frontier.append(child)
    return found


def _normalise(value: str | Path) -> str:
    return str(value).replace("\\", "/").rstrip("/").lower()


def _contains_path(commandline: str, path: str | Path) -> bool:
    return _normalise(path) in _normalise(commandline)


def is_excluded_commandline(commandline: str) -> bool:
    """Never claim an adjacent Claude/Codex/Salad process for a launcher."""
    lowered = _normalise(commandline)
    return any(marker in lowered for marker in _EXCLUDED_MARKERS)


def should_track(
    info: ProcessInfo,
    *,
    root: str | Path,
    launcher: str | Path,
    related_patterns: Sequence[str] = (),
) -> bool:
    """Decide ownership from an exact launcher scope, never from a bare name."""
    if info.pid <= 0 or is_excluded_commandline(info.commandline):
        return False
    commandline = _normalise(info.commandline)
    if any(str(pattern).lower() in commandline for pattern in related_patterns):
        return True
    return _normalise(root) in commandline or _normalise(launcher) in commandline


def _powershell_snapshot() -> dict[int, ProcessInfo]:
    if os.name != "nt":
        return {}
    command = (
        "$ErrorActionPreference='Stop'; "
        "@(Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine," 
        "@{N='CreatedAt';E={if ($_.CreationDate) { "
        "([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds() "
        "} else { $null }}}) | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed local inspection command
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    return parse_snapshot(completed.stdout)


def _append_log(path: Path, event: str, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _same_identity(current: ProcessInfo | None, original: ProcessInfo) -> bool:
    if current is None:
        return False
    return (
        current.pid == original.pid
        and current.name.lower() == original.name.lower()
        and current.commandline == original.commandline
    )


def _write_stop_file(path: Path | None, log: Path) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n", encoding="ascii")
        _append_log(log, "stop-file-written", path=str(path))
    except OSError as exc:
        _append_log(log, "stop-file-error", path=str(path), error=str(exc))


def _ctrl_break(pid: int, log: Path) -> None:
    if os.name != "nt":
        return
    try:
        os.kill(pid, getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        _append_log(log, "graceful-signal", pid=pid, signal="CTRL_BREAK_EVENT")
    except (OSError, ValueError) as exc:
        _append_log(log, "graceful-signal-unavailable", pid=pid, error=str(exc))


def _taskkill(pid: int, *, force: bool, log: Path) -> None:
    command = ["taskkill.exe", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed Windows lifecycle command
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        _append_log(
            log,
            "taskkill",
            pid=pid,
            force=force,
            returncode=completed.returncode,
            stdout=(completed.stdout or "")[-500:],
            stderr=(completed.stderr or "")[-500:],
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _append_log(log, "taskkill-error", pid=pid, force=force, error=str(exc))


def stop_processes(
    tracked: Mapping[int, ProcessInfo],
    *,
    snapshot: Mapping[int, ProcessInfo],
    log: Path,
    grace_s: float = _GRACE_S,
    sleeper: Callable[[float], None] = time.sleep,
    snapshot_fn: Callable[[], dict[int, ProcessInfo]] = _powershell_snapshot,
) -> dict[str, list[int]]:
    """Stop only identity-verified tracked processes, gracefully then bounded."""
    if os.name != "nt":
        return {"requested": [], "forced": []}
    eligible = [
        pid
        for pid, original in tracked.items()
        if pid != os.getpid() and _same_identity(snapshot.get(pid), original)
    ]
    if not eligible:
        return {"requested": [], "forced": []}
    for pid in eligible:
        _ctrl_break(pid, log)
    # The non-forced tree stop lets CMD/Python flush their append-only receipts.
    for pid in eligible:
        _taskkill(pid, force=False, log=log)
    deadline = time.monotonic() + max(0.0, float(grace_s))
    current = dict(snapshot)
    while time.monotonic() < deadline:
        sleeper(0.2)
        refreshed = snapshot_fn()
        if refreshed:
            current = refreshed
        if not any(_same_identity(current.get(pid), tracked[pid]) for pid in eligible):
            break
    forced: list[int] = []
    for pid in eligible:
        if _same_identity(current.get(pid), tracked[pid]):
            _taskkill(pid, force=True, log=log)
            forced.append(pid)
    return {"requested": eligible, "forced": forced}


def run_watcher(
    *,
    scope: str,
    root: Path,
    launcher: Path,
    stop_file: Path | None = None,
    related_patterns: Sequence[str] = (),
    poll_s: float = _POLL_S,
    grace_s: float = _GRACE_S,
    snapshot_fn: Callable[[], dict[int, ProcessInfo]] = _powershell_snapshot,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Watch the owning CMD and reap only children from this launch session."""
    log = root / "runtime" / "logs" / "launcher-lifecycle" / f"{scope}.jsonl"
    if os.name != "nt":
        _append_log(log, "unsupported-platform", platform=os.name)
        return 0
    initial = snapshot_fn()
    parent_pid = os.getppid()
    parent_identity = initial.get(parent_pid)
    if parent_identity is None:
        _append_log(log, "parent-not-found", parent_pid=parent_pid)
        return 0
    baseline = descendant_pids(initial, parent_pid)
    baseline.add(os.getpid())
    watcher_started_at = time.time()
    tracked: dict[int, ProcessInfo] = {}
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    for signum in (getattr(signal, "SIGBREAK", None), signal.SIGINT, signal.SIGTERM):
        if signum is not None:
            try:
                signal.signal(signum, request_stop)
            except (OSError, ValueError):
                pass
    _append_log(
        log,
        "watch-start",
        scope=scope,
        parent_pid=parent_pid,
        parent_name=parent_identity.name,
        launcher=str(launcher),
        baseline_count=len(baseline),
        related_patterns=list(related_patterns),
    )
    last_snapshot = initial
    while not stop_requested:
        current = snapshot_fn()
        if not current:
            _append_log(log, "snapshot-unavailable")
            sleeper(max(0.5, float(poll_s)))
            continue
        last_snapshot = current
        parent = current.get(parent_pid)
        if not _same_identity(parent, parent_identity):
            stop_requested = True
        else:
            candidates = descendant_pids(current, parent_pid) - baseline
            # A child can be created between the launch of this watcher and
            # its first WMI snapshot.  Re-admit only such recent baseline
            # entries; old descendants remain protected from this session.
            candidates.update(
                pid
                for pid in descendant_pids(current, parent_pid)
                if (
                    pid in baseline
                    and pid != os.getpid()
                    and current.get(pid) is not None
                    and current[pid].created_at is not None
                    and current[pid].created_at >= watcher_started_at - 15.0
                )
            )
            for pid in candidates:
                if pid == os.getpid():
                    continue
                info = current.get(pid)
                if info is not None and should_track(
                    info, root=root, launcher=launcher, related_patterns=related_patterns
                ):
                    if pid not in tracked:
                        tracked[pid] = info
                        _append_log(log, "track", pid=pid, parent_pid=info.parent_pid, name=info.name)
            # Related processes (for example the coffre certificateur) are an
            # explicit scope opt-in, never a global name search.
            for info in current.values():
                if info.pid in baseline or info.pid in tracked:
                    continue
                if related_patterns and should_track(
                    info, root=root, launcher=launcher, related_patterns=related_patterns
                ):
                    tracked[info.pid] = info
                    _append_log(log, "track-related", pid=info.pid, name=info.name)
            sleeper(max(0.1, float(poll_s)))
    _append_log(log, "stop-requested", tracked_count=len(tracked), reason="parent-gone-or-signal")
    _write_stop_file(stop_file, log)
    result: dict[str, list[int]] = {"requested": [], "forced": []}
    try:
        result = stop_processes(
            tracked,
            snapshot=last_snapshot,
            log=log,
            grace_s=grace_s,
            snapshot_fn=snapshot_fn,
        )
    except Exception as exc:  # pragma: no cover - defensive last-resort lifecycle log
        _append_log(log, "stop-error", error=repr(exc))
    finally:
        _append_log(log, "watch-end", **result)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stop launcher-owned children on CMD close")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--related-pattern", action="append", default=[])
    parser.add_argument("--poll-s", type=float, default=_POLL_S)
    parser.add_argument("--grace-s", type=float, default=_GRACE_S)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    return run_watcher(
        scope=args.scope,
        root=args.root.resolve(),
        launcher=args.launcher.resolve(),
        stop_file=args.stop_file.resolve() if args.stop_file else None,
        related_patterns=args.related_pattern,
        poll_s=args.poll_s,
        grace_s=args.grace_s,
    )


if __name__ == "__main__":
    raise SystemExit(main())
