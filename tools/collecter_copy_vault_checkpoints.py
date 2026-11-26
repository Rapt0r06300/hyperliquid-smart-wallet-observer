"""Run the forward-only Copy-Vault causal checkpoint companion."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from heartbeat_collecteur import battre  # noqa: E402
from hl_observer.collection.copy_vault_checkpoint_socle import (  # noqa: E402
    copy_vault_checkpoint_source_lock,
)
from hl_observer.collection.copy_vault_checkpoint_tail import (  # noqa: E402
    COMPANION_PROTOCOL,
    CopyVaultCheckpointTail,
)


def run(root: Path, *, interval_s: float = 0.5) -> int:
    # Acquire before reading the input identity/offset. A concurrent atomic lane
    # merge either completes first or is deferred until this process exits.
    with copy_vault_checkpoint_source_lock(root, wait_s=10.0):
        return _run_locked(root, interval_s=interval_s)


def _run_locked(root: Path, *, interval_s: float = 0.5) -> int:
    engine = CopyVaultCheckpointTail(root)
    wrapper_pid = os.getppid()
    while True:
        result = engine.poll_once()
        counters = result["counters"]
        gap_count = result.get("collector_gap_count")
        raw_coverage_status = result.get("coverage_receipt_status")
        coverage_status = (
            raw_coverage_status
            if raw_coverage_status in {"PROVEN", "UNMEASURABLE"}
            else "UNMEASURABLE"
        )
        metriques = {
            "coverage_receipt_status": coverage_status,
            "stale": False,
        }
        for metric in (
            "coverage_receipt_reason",
            "gap_journal_status",
            "gap_journal_reason",
        ):
            value = result.get(metric)
            if value is not None:
                metriques[metric] = value
        for metric, counter in (
            ("checkpoint_expirations", "checkpoints_expired"),
            ("checkpoint_queue_rejections", "pending_overflow_rejected"),
            ("input_rotations", "input_rotations"),
            ("reconnect_backfill_blocked", "reconnect_backfill_blocked"),
            ("invalid_rejected", "invalid_rejected"),
            ("writer_outages", "writer_outages"),
        ):
            value = counters.get(counter, 0)
            if type(value) is int and value >= 0:
                metriques[metric] = value
            else:
                metriques["coverage_receipt_status"] = "UNMEASURABLE"
        if type(gap_count) is int and gap_count >= 0:
            metriques["gaps_critiques"] = gap_count
        else:
            metriques["coverage_receipt_status"] = "UNMEASURABLE"
        battre(
            root,
            "copy-vault-checkpoints",
            n_ecrites=int(result["captured"]),
            dernier_exchange_ts=engine.state.get("updated_at_ms"),
            note=(
                "forward-only lines=%d pending=%d captured=%d expired=%d"
                % (
                    result["lines"],
                    result["pending"],
                    counters.get("checkpoints_captured", 0),
                    counters.get("checkpoints_expired", 0),
                )
            ),
            pid=wrapper_pid,
            protocol=COMPANION_PROTOCOL,
            metriques=metriques,
        )
        time.sleep(max(0.1, float(interval_s)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--interval-s", type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        return run(Path(args.root).resolve(), interval_s=args.interval_s)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
