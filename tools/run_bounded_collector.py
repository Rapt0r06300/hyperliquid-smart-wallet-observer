"""Run one read-only collector under an expiring campaign lease.

This is deliberately separate from ``boucle_collecteur.cmd``: the latter is
owned by the visible launcher session.  This runner is used only by explicit
economic evidence campaigns and terminates persistent workers when their lease
expires or is replaced.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.collector_lease import validate_lease  # noqa: E402

_LOG_MAX_BYTES = 4 * 1024 * 1024
_LOG_BACKUPS = 3


class _RotatingLog:
    """Thread-safe bounded byte log shared by the child-output pump and runner."""

    def __init__(
        self, path: Path, *, max_bytes: int = _LOG_MAX_BYTES,
        backup_count: int = _LOG_BACKUPS,
    ) -> None:
        if max_bytes <= 0 or backup_count < 0:
            raise ValueError("invalid bounded log limits")
        self.path = path
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self._size = 0
        self._handle = path.open("wb")

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    def _rotate(self) -> None:
        self._handle.close()
        try:
            for index in range(self.backup_count, 0, -1):
                source = self.path if index == 1 else self._backup_path(index - 1)
                target = self._backup_path(index)
                if not source.exists():
                    continue
                source.replace(target)
        except OSError:
            # Keep collection running if antivirus/indexing temporarily blocks a
            # rotation. The pump still drains the child even if logging fails.
            self._handle = self.path.open("ab")
            self._size = self.path.stat().st_size if self.path.exists() else 0
            return
        else:
            self._handle = self.path.open("wb")
            self._size = 0

    def write(self, payload: bytes) -> None:
        if not payload:
            return
        with self._lock:
            if self._size and self._size + len(payload) > self.max_bytes:
                self._rotate()
            self._handle.write(payload)
            self._handle.flush()
            self._size += len(payload)

    def write_text(self, message: str) -> None:
        self.write(message.encode("utf-8", errors="replace"))

    def close(self) -> None:
        with self._lock:
            self._handle.close()

    def __enter__(self) -> _RotatingLog:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _pump_child_output(stream: Any, output: _RotatingLog) -> None:
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            try:
                output.write(chunk)
            except (OSError, ValueError):
                # Continue draining stdout so a full pipe cannot stall a worker.
                continue
    except (OSError, ValueError):
        return
    finally:
        stream.close()


def _stop_child(child: subprocess.Popen[bytes], *, grace_s: float = 5.0) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    child.kill()
    child.wait(timeout=grace_s)


def run(
    *,
    root: Path,
    name: str,
    script: Path,
    interval_s: float,
    lease_file: Path,
    lease_token: str,
    script_args: list[str],
) -> int:
    log = root / "runtime" / "logs" / f"economic-{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        try:
            with log.open("rb") as previous:
                previous.seek(0, os.SEEK_END)
                previous_size = previous.tell()
                previous.seek(max(0, previous_size - _LOG_MAX_BYTES))
                previous_tail = previous.read(_LOG_MAX_BYTES)
            log.with_suffix(log.suffix + ".prev").write_bytes(previous_tail)
        except OSError:
            # Rotation is diagnostic only; collection must not die because an
            # antivirus briefly holds the previous log on Windows.
            pass
    with _RotatingLog(log) as output:
        output.write_text(f"bounded collector={name} script={script} interval={interval_s}s\n")
        output.write_text("safety=READ_ONLY lease_enforced=true\n")
        while True:
            valid, reason, payload = validate_lease(lease_file, lease_token, root)
            if not valid:
                output.write_text(f"[bounded-stop] {reason}\n")
                return 0
            output.write_text(
                "[pass] lease=%s expires_at_ms=%s\n"
                % (payload.get("lease_id"), payload.get("expires_at_ms"))
            )
            command = [sys.executable, str(script), *script_args]
            child_env = {**os.environ, "PYTHONPATH": str(root / "src")}
            child_env["PYTHONUNBUFFERED"] = "1"
            child_env.pop("HYPERSMART_COLLECTOR_LEASE_TOKEN", None)
            child = subprocess.Popen(  # noqa: S603 - local registry script only
                command,
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=child_env,
                bufsize=0,
            )
            assert child.stdout is not None
            output_pump = threading.Thread(
                target=_pump_child_output,
                args=(child.stdout, output),
                name=f"log-pump-{name}",
                daemon=True,
            )
            output_pump.start()
            try:
                while child.poll() is None:
                    valid, reason, _ = validate_lease(lease_file, lease_token, root)
                    if not valid:
                        output.write_text(f"[bounded-stop-worker] {reason}\n")
                        _stop_child(child)
                        return 0
                    time.sleep(1.0)
            finally:
                _stop_child(child)
                output_pump.join(timeout=10.0)
            output.write_text(f"[pass-end] returncode={child.returncode}\n")
            deadline = time.monotonic() + max(0.0, interval_s)
            while time.monotonic() < deadline:
                valid, reason, _ = validate_lease(lease_file, lease_token, root)
                if not valid:
                    output.write_text(f"[bounded-stop-wait] {reason}\n")
                    return 0
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--interval-s", type=float, required=True)
    parser.add_argument("--lease-file", required=True)
    parser.add_argument("--lease-token")
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    script_args = args.script_args[1:] if args.script_args[:1] == ["--"] else args.script_args
    root = Path(args.root).resolve()
    script = (root / args.script).resolve()
    if not script.is_file() or root not in script.parents:
        print("bounded collector refused: script outside project or missing", flush=True)
        return 2
    lease_token = args.lease_token or os.environ.get("HYPERSMART_COLLECTOR_LEASE_TOKEN", "")
    if not lease_token:
        print("bounded collector refused: lease token missing", flush=True)
        return 2
    return run(
        root=root,
        name=args.name,
        script=script,
        interval_s=args.interval_s,
        lease_file=Path(args.lease_file),
        lease_token=lease_token,
        script_args=script_args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
