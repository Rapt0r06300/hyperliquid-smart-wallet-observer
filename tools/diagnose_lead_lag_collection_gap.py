"""Autopsie FULL/COLD des chocs Lead-Lag et de la disponibilité du carnet causal.

Le seuil 8 bps est un seuil de DIAGNOSTIC destiné à expliquer les deux événements
rares déjà observés. Il ne remplace jamais le seuil économique figé du replay.
Le rapport produit n'est pas une certification de PnL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.lead_lag_collection_gap_diagnostic import (  # noqa: E402
    diagnose_shock_book_availability,
)
from hl_observer.backtesting.lead_lag_queue_replay import (  # noqa: E402
    MAX_BOOK_DELAY_MS,
    SHOCK_THRESHOLD_BPS,
    detect_rolling_shocks,
)
from hl_observer.backtesting.lead_lag_source_alignment import (  # noqa: E402
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)
from hl_observer.datasets.source_discovery import (  # noqa: E402
    is_dataset_workspace,
    load_family_source_paths,
)
from hl_observer.simulation.lead_lag_l2_history import (  # noqa: E402
    load_market_microstructure_event_windows,
)

DEFAULT_DIAGNOSTIC_THRESHOLD_BPS = 8.0
REPORT_RELATIVE_PATH = Path(
    "runtime/reports/economic_campaigns/lead_lag_collection_gap_diagnostic.json"
)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_diagnostic(
    root: Path,
    *,
    diagnostic_threshold_bps: float = DEFAULT_DIAGNOSTIC_THRESHOLD_BPS,
    max_book_delay_ms: int = MAX_BOOK_DELAY_MS,
) -> dict:
    root = root.resolve()
    dataset_mode = is_dataset_workspace(root)
    candidates = load_family_source_paths(root, "lead_lag") if dataset_mode else None
    aligned_sources, alignment_meta = select_aligned_bbo_sources(
        root,
        candidates=candidates,
    )
    lead_tape, lead_meta = load_aligned_binance_trade_tape(root, aligned_sources)
    trades = (lead_tape.get("ETH") or {}).get("TRADE") or ()
    diagnostic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=float(diagnostic_threshold_bps),
    )
    economic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=float(SHOCK_THRESHOLD_BPS),
    )
    event_timestamps = [int(row["trigger_ts_ms"]) for row in diagnostic_shocks]
    l2_history, public_trades, microstructure_meta = load_market_microstructure_event_windows(
        root,
        event_timestamps,
    )
    diagnostic = diagnose_shock_book_availability(
        diagnostic_shocks,
        l2_history.get("ETH", ()),
        max_book_delay_ms=max_book_delay_ms,
    )
    payload = {
        "schema_version": "hypersmart.lead_lag_full_gap_autopsy.v1",
        "dataset_workspace": dataset_mode,
        "diagnostic_threshold_bps": float(diagnostic_threshold_bps),
        "economic_threshold_bps_unchanged": float(SHOCK_THRESHOLD_BPS),
        "diagnostic_threshold_changes_economic_strategy": False,
        "max_book_delay_ms": int(max_book_delay_ms),
        "diagnostic_shock_count": len(diagnostic_shocks),
        "economic_shock_count": len(economic_shocks),
        "source_alignment": alignment_meta,
        "lead_tape": lead_meta,
        "microstructure": microstructure_meta,
        "diagnostic": diagnostic,
        "public_trade_rows_loaded": sum(len(rows) for rows in public_trades.values()),
        "verdict_scope": "DATA_QUALITY_DIAGNOSTIC_ONLY_NOT_PNL_CERTIFICATION",
        "paper_read_only": True,
        "real_execution": False,
    }
    _write_json_atomic(root / REPORT_RELATIVE_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--diagnostic-threshold-bps",
        type=float,
        default=DEFAULT_DIAGNOSTIC_THRESHOLD_BPS,
    )
    parser.add_argument("--max-book-delay-ms", type=int, default=MAX_BOOK_DELAY_MS)
    args = parser.parse_args(argv)
    try:
        payload = run_diagnostic(
            Path(args.root),
            diagnostic_threshold_bps=args.diagnostic_threshold_bps,
            max_book_delay_ms=args.max_book_delay_ms,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"LEAD_LAG_GAP_DIAGNOSTIC_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 2
    diagnostic = payload["diagnostic"]
    print(
        "LEAD_LAG_GAP_DIAGNOSTIC_OK "
        f"diag_shocks={payload['diagnostic_shock_count']} "
        f"economic_shocks={payload['economic_shock_count']} "
        f"within_750ms={diagnostic['causal_book_within_limit_count']} "
        f"explicit_gaps={diagnostic['explicit_collector_gap_count']}",
        flush=True,
    )
    print(f"report={Path(args.root).resolve() / REPORT_RELATIVE_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
