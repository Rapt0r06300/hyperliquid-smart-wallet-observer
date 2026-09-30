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
from hl_observer.collection.copy_vault_checkpoint_tail import (  # noqa: E402
    COMPANION_PROTOCOL,
    CopyVaultCheckpointTail,
)


def run(root: Path, *, interval_s: float = 0.5) -> int:
    engine = CopyVaultCheckpointTail(root)
    wrapper_pid = os.getppid()
    while True:
        result = engine.poll_once()
        counters = result["counters"]
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
