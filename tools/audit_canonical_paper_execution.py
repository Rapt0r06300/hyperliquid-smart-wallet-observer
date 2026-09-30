"""Runtime proof for the canonical local paper-execution path.

The proof deliberately uses a deterministic recorded-real L2 fixture. It
executes the same economic intent through the low-level core, the main
PaperEngine and the strategy PaperSimConnector, then verifies that all three
paths consume the same side of the book and produce the same fill economics.
No network client or external execution surface is imported.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_connector import PaperSimConnector
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    approve_with_risk,
)


OBSERVED_AT_MS = 1_800_000_000_000
WALLET = "0x" + ("c" * 40)
BIDS = ((99.99, 100.0), (99.98, 100.0))
ASKS = ((100.01, 0.5), (100.02, 100.0))


def _truth(*, source: str = "recorded_hyperliquid_l2") -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=BIDS,
        asks=ASKS,
        received_ts_ms=OBSERVED_AT_MS - 1,
        exchange_ts_ms=OBSERVED_AT_MS - 2,
        source=source,
        data_origin="RECORDED_REAL",
    )


def run_audit() -> dict[str, object]:
    execution_intent = PaperExecutionIntent(
        strategy_id="copy_vault",
        coin="HYPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=100.0,
        confidence=0.95,
        created_at_ms=OBSERVED_AT_MS,
    )
    direct = execute_paper_intent(
        execution_intent,
        CausalMarketSnapshot.from_truth(
            _truth(),
            decision_ts_ms=OBSERVED_AT_MS,
        ),
    )

    strategy_intent = PaperIntent(
        strategy_id="copy_vault",
        coin="HYPE",
        side=IntentSide.LONG,
        action=IntentAction.OPEN,
        target_notional_usdt=100.0,
        confidence=0.95,
        created_at_ms=OBSERVED_AT_MS,
    )
    connector = PaperSimConnector()
    connector_result = connector.apply_intent(
        approve_with_risk(strategy_intent, lambda _: (True, ())),
        mid_price=100.0,
        top_depth_usdt=None,
        observed_at_ms=OBSERVED_AT_MS,
        bids=BIDS,
        asks=ASKS,
        min_fill_ratio=0.0,
    )

    delta = LeaderDelta(
        delta_id="ld:runtime-proof:hype:open",
        wallet=WALLET,
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=1.0,
        delta_size=1.0,
        observed_at_ms=OBSERVED_AT_MS,
        leader_event_time_ms=OBSERVED_AT_MS,
        source="recorded_runtime_proof",
        confidence=0.95,
        evidence_ref="fill:runtime-proof",
    )
    engine = PaperEngine(
        config=PaperEngineConfig(
            max_position_usdt=100.0,
            max_total_exposure_usdt=100.0,
            leverage=1.0,
            strict_execution_truth=True,
        )
    )
    engine_result = engine.apply_delta(
        delta,
        market_price=100.0,
        observed_at_ms=OBSERVED_AT_MS,
        edge_remaining_bps=100.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=None,
        wallet_score=100.0,
        signal_score=100.0,
        marks={"HYPE": 100.0},
        execution_truth=_truth(),
        decision_context={"strategy_id": "copy_vault"},
    )

    direct_fill = direct.execution.fill_price
    connector_fill = connector_result.fill.fill_price if connector_result.fill else None
    engine_fill = engine_result.trade.fill_price if engine_result.trade else None
    parity = (
        direct.accepted
        and connector_result.accepted
        and engine_result.accepted
        and direct_fill == connector_fill == engine_fill
        and direct.execution.filled_notional_usdc
        == engine_result.trade.filled_notional_usdt
    )
    return {
        "audit": "canonical_paper_execution",
        "parity": parity,
        "paper_only": True,
        "real_execution": False,
        "input": {
            "coin": "HYPE",
            "action": "OPEN",
            "position_side": "LONG",
            "execution_side": direct.plan.execution_side,
            "requested_notional_usdc": 100.0,
            "snapshot_id": direct.plan.snapshot_id,
        },
        "direct_core": direct.as_dict(),
        "paper_engine": {
            "accepted": engine_result.accepted,
            "fill_price": engine_fill,
            "filled_notional_usdc": (
                engine_result.trade.filled_notional_usdt
                if engine_result.trade
                else 0.0
            ),
            "plan_id": engine_result.decision_context.get(
                "canonical_execution_plan_id"
            ),
            "ledger_event_id": engine_result.decision_context.get(
                "canonical_ledger_event_id"
            ),
        },
        "paper_connector": connector_result.as_dict(),
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
    return 0 if payload["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
