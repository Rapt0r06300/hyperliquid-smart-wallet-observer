from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_protocol import (
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.backtesting.copy_vault_vnext_train import explore_copy_vault_vnext_train


def _row() -> dict:
    return {
        "trade_id": "train-0xa-ETH-2000000000000",
        "vault": "0xa",
        "coin": "ETH",
        "direction": 1,
        "signal_ts_ms": 2_000_000_000_000,
        "walk_forward_segment": "train",
        "regime_id": "trend",
        "liquidatable_net": True,
        "public_entity_id": "entity-a",
        "entry_price": 2_000.0,
        "exit_price": 2_001.0,
        "notional_usd": 100.0,
        "entry_capacity_usd": 1_000.0,
        "exit_capacity_usd": 1_000.0,
        "reference_lag_ms": 0,
        "entry_target_lag_ms": 0,
        "exit_target_lag_ms": 0,
        "observed_latency_ms": 0,
        "gross_pnl_usd": 1.0,
        "fees_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": 1.0,
    }


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("reference_lag_ms", MAX_REFERENCE_LAG_MS),
        ("entry_target_lag_ms", MAX_TARGET_LAG_MS),
        ("exit_target_lag_ms", MAX_TARGET_LAG_MS),
    ],
)
def test_copy_vnext_rejects_execution_evidence_beyond_protocol_freshness_limit(
    field: str, limit: int
) -> None:
    row = _row()
    row[field] = limit + 1

    result = explore_copy_vault_vnext_train(
        {"provisional_without_physical_freeze": False, "trades": [row]}
    )

    assert result["train_rows_seen"] == 0
