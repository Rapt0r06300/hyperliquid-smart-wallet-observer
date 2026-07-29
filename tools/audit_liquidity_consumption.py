"""Runtime proof that paper strategies share finite visible L2 liquidity."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import (
    LiquidityConsumptionLedger,
)


NOW_MS = 1_800_000_000_000


def _truth(snapshot_id: str) -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=((99.0, 1.0),),
        asks=((100.0, 1.0),),
        received_ts_ms=NOW_MS,
        exchange_ts_ms=NOW_MS - 1,
        source="hyperliquid",
        snapshot_id=snapshot_id,
        data_origin="RECORDED_REAL",
    )


def _intent(strategy_id: str) -> PaperExecutionIntent:
    return PaperExecutionIntent(
        strategy_id=strategy_id,
        coin="HYPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=60.0,
        confidence=0.95,
        created_at_ms=NOW_MS,
    )


def _execute(
    strategy_id: str,
    truth: ExecutionTruth,
    ledger: LiquidityConsumptionLedger,
):
    return execute_paper_intent(
        _intent(strategy_id),
        CausalMarketSnapshot.from_truth(truth, decision_ts_ms=NOW_MS),
        liquidity_ledger=ledger,
    )


def run_audit() -> dict[str, object]:
    ledger = LiquidityConsumptionLedger()
    truth = _truth("book:one")
    first = _execute("first", truth, ledger)
    second = _execute("second", truth, ledger)
    retry = _execute("first", truth, ledger)
    exhausted = _execute("third", truth, ledger)
    fresh = _execute("fresh", _truth("book:two"), ledger)
    total_quantity = first.execution.filled_quantity + second.execution.filled_quantity
    checks = {
        "same_snapshot_never_overfilled": abs(total_quantity - 1.0) < 1e-12,
        "second_plan_partial": second.execution.partial
        and second.execution.filled_notional_usdc == 40.0,
        "retry_idempotent": retry.execution == first.execution
        and retry.liquidity_reservation is not None
        and retry.liquidity_reservation.replayed,
        "exhausted_snapshot_refused": exhausted.execution.reason
        == "LIQUIDITY_ALREADY_CONSUMED",
        "new_snapshot_replenishes": fresh.execution.filled_notional_usdc == 60.0,
    }
    return {
        "audit": "liquidity_consumption",
        "passed": all(checks.values()),
        "checks": checks,
        "first": first.as_dict(),
        "second": second.as_dict(),
        "retry": retry.as_dict(),
        "exhausted": exhausted.as_dict(),
        "fresh_snapshot": fresh.as_dict(),
        "ledger": [asdict(row) for row in ledger.snapshot()],
        "paper_only": True,
        "real_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_audit()
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
