"""Produce a deterministic runtime proof for capital/exposure semantics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.simulation.paper_ledger import PaperLedger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ledger = PaperLedger(
        starting_balance_usdc=1_000.0,
        session_id="audit:capital-accounting:v2",
    )
    ledger.open_position(
        coin="PAIR",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=10.0,
        leg_notional_usd=(100.0, 100.0),
        leg_direction=(1, -1),
        liquidation_buffer_bps=300.0,
        position_id="pair:audit",
        refs={"source": "deterministic_runtime_audit"},
    )
    ledger.mark_to_market(
        {"PAIR": 101.0},
        liquidatable_marks={"pair:audit": 100.5},
        timestamp_ms=2_000,
    )
    before_reduce = ledger.snapshot()
    ledger.reduce_or_close(
        coin="PAIR",
        side="LONG",
        quantity=0.5,
        fill_price=101.0,
        timestamp_ms=3_000,
        fee_bps=0.0,
        position_id="pair:audit",
        refs={"source": "deterministic_runtime_audit"},
    )
    ledger.mark_to_market(
        {"PAIR": 101.0},
        liquidatable_marks={"pair:audit": 100.75},
        timestamp_ms=4_000,
    )
    after_reduce = ledger.snapshot()

    before_capital = before_reduce["capital_accounting"]
    after_capital = after_reduce["capital_accounting"]
    checks = {
        "gross_sums_both_legs": before_capital["gross_exposure_usd"] == 200.0,
        "margin_is_explicit": before_capital["margin_locked_usd"] == 20.0,
        "hedged_net_is_zero": before_capital["net_directional_exposure_usd"] == 0.0,
        "liquidatable_pnl_authoritative": (
            before_capital["liquidatable_pnl_usd"] == 0.5
            and before_reduce["authoritative_equity_usdc"] == 1_000.5
        ),
        "partial_close_scales_exposure": (
            after_capital["gross_exposure_usd"] == 100.0
            and after_capital["margin_locked_usd"] == 10.0
        ),
        "turnover_counts_open_and_close": after_capital["turnover_usd"] == 300.0,
        "event_chain_valid": ledger.verify_event_chain(),
    }
    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "before_reduce": before_reduce,
        "after_reduce": after_reduce,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
