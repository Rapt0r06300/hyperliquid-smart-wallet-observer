"""Low-priority local watchdog for the bounded paper-data campaign."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.bounded_collection import (  # noqa: E402
    STATE_RELPATH,
    ensure_bounded_collectors,
)

DEFAULT_NAMES = (
    "allmids-collector",
    "bbo-collector",
    "carnet-collector",
    "venues-collector",
    "marks-collector",
    "liq-collector",
    "overshoot-collector",
    "vault-collector",
    "scorer-vaults",
    "backfill-fills",
    "backfill-candles-vaults",
    "userfills-live",
    "copy-vault-checkpoints",
)


def _idle_priority() -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(  # type: ignore[attr-defined]
            ctypes.windll.kernel32.GetCurrentProcess(), 0x40
        )


def _requested_names(root: Path) -> list[str]:
    try:
        state = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
        requested = [str(name) for name in state.get("requested") or () if name]
    except (OSError, TypeError, ValueError):
        requested = []
    return list(dict.fromkeys(requested or DEFAULT_NAMES))


def _append_log(root: Path, payload: dict[str, Any]) -> None:
    path = root / "runtime" / "logs" / "economic-collector-watchdog.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_watchdog(
    root: Path,
    *,
    interval_s: float,
    duration_s: float,
    ensure_fn: Callable[..., dict[str, Any]] = ensure_bounded_collectors,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    max_passes: int | None = None,
) -> int:
    deadline = monotonic_fn() + max(0.0, float(duration_s))
    passes = 0
    while monotonic_fn() < deadline:
        names = _requested_names(root)
        try:
            result = ensure_fn(
                root,
                names,
                duration_s=float(duration_s),
                startup_wait_s=5.0,
            )
            record = {
                "ts_ms": int(time.time() * 1000),
                "status": result.get("status"),
                "requested": names,
                "active": sorted((result.get("actifs") or {}).keys()),
                "missing": list(result.get("manquants") or ()),
                "lease_id": (result.get("lease") or {}).get("lease_id"),
                "paper_read_only": result.get("paper_read_only") is True,
                "real_execution": False,
            }
        except Exception as exc:  # noqa: BLE001 - watchdog must survive a transient failure
            record = {
                "ts_ms": int(time.time() * 1000),
                "status": "WATCH_PASS_ERROR",
                "requested": names,
                "error": f"{type(exc).__name__}: {exc}",
                "paper_read_only": True,
                "real_execution": False,
            }
        _append_log(root, record)
        passes += 1
        if max_passes is not None and passes >= int(max_passes):
            break
        remaining = deadline - monotonic_fn()
        if remaining <= 0:
            break
        sleep_fn(min(max(1.0, float(interval_s)), remaining))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--interval-s", type=float, default=30.0)
    parser.add_argument("--duration-s", type=float, default=7 * 24 * 60 * 60)
    args = parser.parse_args(argv)
    _idle_priority()
    return run_watchdog(
        Path(args.root).resolve(),
        interval_s=args.interval_s,
        duration_s=args.duration_s,
    )


if __name__ == "__main__":
    raise SystemExit(main())
