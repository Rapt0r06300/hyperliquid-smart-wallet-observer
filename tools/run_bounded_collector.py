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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.collector_lease import validate_lease  # noqa: E402

_LOG_MAX_BYTES = 2 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


class _BoundedLog:
    """Append runner and child output to a small rotating UTF-8 log set."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = _LOG_MAX_BYTES,
        backup_count: int = _LOG_BACKUP_COUNT,
    ) -> None:
        if max_bytes <= 0 or backup_count < 0:
            raise ValueError("invalid bounded log limits")
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.backup_count = int(backup_count)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for candidate in (
            self.path,
            *(self.path.with_name(f"{self.path.name}.{index}")
              for index in range(1, self.backup_count + 1)),
        ):
            self._trim_existing(candidate)

    def _trim_existing(self, path: Path) -> None:
        if path.is_symlink():
            raise OSError("refusing symlinked collector log")
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size <= self.max_bytes:
            return
        with path.open("rb") as handle:
            handle.seek(size - self.max_bytes)
            tail = handle.read(self.max_bytes)
        path.write_bytes(tail)

    def __enter__(self) -> _BoundedLog:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.flush()

    def write(self, value: str) -> int:
        encoded = str(value).encode("utf-8", errors="replace")
        self.write_bytes(encoded)
        return len(value)

    def write_bytes(self, value: bytes) -> None:
        for offset in range(0, len(value), self.max_bytes):
            chunk = value[offset:offset + self.max_bytes]
            with self._lock:
                if self.path.is_symlink():
                    raise OSError("refusing symlinked collector log")
                current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size and current_size + len(chunk) > self.max_bytes:
                    self._rollover()
                with self.path.open("ab") as handle:
                    handle.write(chunk)

    def _rollover(self) -> None:
        if self.backup_count == 0:
            self.path.write_bytes(b"")
            return
        for index in range(self.backup_count, 0, -1):
            source = (
                self.path.with_name(f"{self.path.name}.{index - 1}")
                if index > 1 else self.path
            )
            target = self.path.with_name(f"{self.path.name}.{index}")
            if source.is_symlink() or target.is_symlink():
                raise OSError("refusing symlinked collector log backup")
            if source.exists():
                os.replace(source, target)

    def flush(self) -> None:
        # Each append opens and closes the file, so all bytes are already flushed.
        return None


def _pump_child_output(pipe, output: _BoundedLog) -> None:
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                return
            output.write_bytes(chunk)
    except (OSError, ValueError):
        # Child termination may close the pipe while the pump is waking up.
        return


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
    with _BoundedLog(log) as output:
        output.write(f"bounded collector={name} script={script} interval={interval_s}s\n")
        output.write("safety=READ_ONLY lease_enforced=true\n")
        while True:
            valid, reason, payload = validate_lease(lease_file, lease_token, root)
            if not valid:
                output.write(f"[bounded-stop] {reason}\n")
                return 0
            output.write(
                f"[pass] lease={payload.get('lease_id')} "
                f"expires_at_ms={payload.get('expires_at_ms')}\n"
            )
            command = [sys.executable, str(script), *script_args]
            child_env = {**os.environ, "PYTHONPATH": str(root / "src")}
            child_env.pop("HYPERSMART_COLLECTOR_LEASE_TOKEN", None)
            child = subprocess.Popen(  # noqa: S603 - local registry script only
                command,
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=child_env,
            )
            assert child.stdout is not None
            pump = threading.Thread(
                target=_pump_child_output, args=(child.stdout, output),
                name=f"collector-log-{name}", daemon=True,
            )
            pump.start()
            try:
                while child.poll() is None:
                    valid, reason, _ = validate_lease(lease_file, lease_token, root)
                    if not valid:
                        output.write(f"[bounded-stop-worker] {reason}\n")
                        _stop_child(child)
                        return 0
                    time.sleep(1.0)
            finally:
                _stop_child(child)
                pump.join(timeout=5.0)
                if pump.is_alive() and child.stdout is not None:
                    child.stdout.close()
                    pump.join(timeout=1.0)
            output.write(f"[pass-end] returncode={child.returncode}\n")
            deadline = time.monotonic() + max(0.0, interval_s)
            while time.monotonic() < deadline:
                valid, reason, _ = validate_lease(lease_file, lease_token, root)
                if not valid:
                    output.write(f"[bounded-stop-wait] {reason}\n")
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
