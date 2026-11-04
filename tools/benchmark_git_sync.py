"""Read-only latency benchmark for the code-only Git synchronizer."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import time
from pathlib import Path
from typing import Sequence

from tools.alina_git_code_sync import Synchronizer


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _inventory_seconds(root: Path, git: str) -> tuple[float, int]:
    synchronizer = Synchronizer(root, git=git, dry_run=True)
    output = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(output):
        synchronizer._inventory(refresh=True)
    elapsed = time.perf_counter() - started
    commands = synchronizer.report.get("git_commands", [])
    return elapsed, len(commands) if isinstance(commands, list) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure local Git inventory latency without mutation."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--git", default="git")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    root = args.root.resolve()
    warmup_seconds, warmup_commands = _inventory_seconds(root, args.git)
    samples: list[float] = []
    command_counts: list[int] = []
    for _ in range(args.runs):
        elapsed, command_count = _inventory_seconds(root, args.git)
        samples.append(elapsed)
        command_counts.append(command_count)

    payload = {
        "root": str(root),
        "runs": args.runs,
        "warmup_seconds": round(warmup_seconds, 6),
        "warmup_git_commands": warmup_commands,
        "inventory_seconds": [round(value, 6) for value in samples],
        "inventory_p50_seconds": round(_percentile(samples, 0.50), 6),
        "inventory_p95_seconds": round(_percentile(samples, 0.95), 6),
        "git_commands": command_counts,
        "mutations": [],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
