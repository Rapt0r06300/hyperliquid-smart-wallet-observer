"""Build a diagnostic-only causal-book audit for Lead-Lag FULL/COLD workspaces.

This tool deliberately lives outside the economic selector. The 8 bps trigger
is used only to autopsy source coverage; it cannot alter the frozen 20 bps
economic hypothesis or certify PnL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)
from hl_observer.backtesting.lead_lag_queue_replay import detect_rolling_shocks
from hl_observer.backtesting.lead_lag_source_alignment import (
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)
from hl_observer.datasets.source_discovery import load_family_source_paths
from hl_observer.simulation.lead_lag_l2_history import load_market_microstructure_event_windows


def run(root: Path) -> tuple[Path, dict]:
    root = root.resolve()
    lead_sources = load_family_source_paths(root, "lead_lag")
    aligned_sources, alignment_meta = select_aligned_bbo_sources(root, candidates=lead_sources)
    tape, tape_meta = load_aligned_binance_trade_tape(root, aligned_sources)
    shocks = detect_rolling_shocks(
        (tape.get("ETH") or {}).get("TRADE") or (),
        threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    )
    books, _trades, microstructure_meta = load_market_microstructure_event_windows(
        root,
        [int(shock["trigger_ts_ms"]) for shock in shocks],
    )
    result = diagnose_causal_book_coverage(shocks, books, microstructure_meta)
    result["diagnostic_shock_threshold_bps"] = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
    result["economic_threshold_unchanged"] = True
    result["economic_selection_eligible"] = False
    result["source_alignment"] = {
        **alignment_meta,
        "aligned_lead_tape": tape_meta,
    }
    result["microstructure_history"] = microstructure_meta
    target = root / "runtime" / "reports" / "economic_campaigns" / "raw" / "lead_lag_causal_coverage.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    target, result = run(Path(args.root))
    print(
        "LEAD_LAG_CAUSAL_AUDIT "
        f"threshold={DIAGNOSTIC_SHOCK_THRESHOLD_BPS:.1f}bps "
        f"shocks={result['shock_count']} classes={result['classifications']} report={target}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
