"""Refuse closure work when the canonical phase changes after checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .phase_gate import load as load_phase_state
except ImportError:  # Script execution from ``python tools/...``.
    from phase_gate import load as load_phase_state


def verify_phase_snapshot(
    state_path: str | Path,
    *,
    phase: str,
    stage: str,
    epoch: str,
    source_collection_epoch: str,
    cutoff: str,
) -> dict[str, str]:
    """Validate canonical state and require it to match the initial workflow read."""
    state = load_phase_state(Path(state_path))
    actual = {
        "phase": str(state["phase"]),
        "stage": str(state.get("analysis_stage") or ""),
        "epoch": str(state["epoch"]),
        "source_collection_epoch": str(state.get("source_collection_epoch") or ""),
        "cutoff": str(state.get("collection_cutoff_at_utc") or ""),
    }
    expected = {
        "phase": phase,
        "stage": stage,
        "epoch": epoch,
        "source_collection_epoch": source_collection_epoch,
        "cutoff": cutoff,
    }
    changed = [
        f"{key}: initial={expected[key]!r}, current={actual[key]!r}"
        for key in expected
        if actual[key] != expected[key]
    ]
    if changed:
        raise ValueError("phase snapshot changed; refusing closure work: " + "; ".join(changed))
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="control/alina-phase.json")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--epoch", required=True)
    parser.add_argument("--source-collection-epoch", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()

    try:
        current = verify_phase_snapshot(
            args.state,
            phase=args.phase,
            stage=args.stage,
            epoch=args.epoch,
            source_collection_epoch=args.source_collection_epoch,
            cutoff=args.cutoff,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "canonical phase snapshot verified: "
        f"{current['phase']} stage={current['stage'] or '(none)'} "
        f"epoch={current['epoch']} source_collection_epoch="
        f"{current['source_collection_epoch'] or '(none)'} cutoff="
        f"{current['cutoff'] or '(none)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
