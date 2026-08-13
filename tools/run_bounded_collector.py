"""Run one read-only collector under an expiring campaign lease.

This is deliberately separate from ``boucle_collecteur.cmd``: the latter is
owned by the visible launcher session.  This runner is used only by explicit
economic evidence campaigns and terminates persistent workers when their lease
expires or is replaced.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.collector_lease import validate_lease  # noqa: E402


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
            shutil.copyfile(log, log.with_suffix(log.suffix + ".prev"))
        except OSError:
            # Rotation is diagnostic only; collection must not die because an
            # antivirus briefly holds the previous log on Windows.
            pass
    with log.open("w", encoding="utf-8", buffering=1) as output:
        output.write(f"bounded collector={name} script={script} interval={interval_s}s\n")
        output.write("safety=READ_ONLY lease_enforced=true\n")
        while True:
            valid, reason, payload = validate_lease(lease_file, lease_token, root)
            if not valid:
                output.write(f"[bounded-stop] {reason}\n")
                return 0
            output.write(
                "[pass] lease=%s expires_at_ms=%s\n"
                % (payload.get("lease_id"), payload.get("expires_at_ms"))
            )
            command = [sys.executable, str(script), *script_args]
            child_env = {**os.environ, "PYTHONPATH": str(root / "src")}
            child_env.pop("HYPERSMART_COLLECTOR_LEASE_TOKEN", None)
            child = subprocess.Popen(  # noqa: S603 - local registry script only
                command,
                cwd=str(root),
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=child_env,
            )
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
