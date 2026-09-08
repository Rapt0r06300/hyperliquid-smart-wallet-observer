from __future__ import annotations

from hl_observer.backtesting.copy_vault_vnext_train import explore_copy_vault_vnext_train


def _row(*, ts: int, vault: str, coin: str, regime_id: str) -> dict:
    return {
        "trade_id": f"train-{vault}-{coin}-{ts}",
        "metaorder_id": f"meta-{vault}-{coin}-{ts}",
        "vault": vault,
        "coin": coin,
        "direction": 1,
        "signal_ts_ms": ts,
        "walk_forward_segment": "train",
        "regime_id": regime_id,
        "liquidatable_net": True,
        "public_entity_id": f"entity-{vault.lower()}",
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


def test_copy_vnext_rejects_train_candidate_concentrated_in_one_causal_regime() -> None:
    day_ms = 86_400_000
    rows: list[dict] = []
    for day_index in range(4):
        base = (40_000 + day_index) * day_ms
        coin = "ETH" if day_index % 2 == 0 else "SOL"
        for wallet_index in range(3):
            rows.append(
                _row(
                    ts=base + (wallet_index + 1) * 1_000,
                    vault=f"0x{wallet_index}",
                    coin=coin,
                    regime_id="trend-low-vol",
                )
            )

    result = explore_copy_vault_vnext_train(
        {"provisional_without_physical_freeze": False, "trades": rows}
    )

    assert result["train_rows_seen"] == 12
    assert result["selection_eligible"] is False
    assert result["selected"] is None
    assert all(variant["distinct_regimes"] == 1 for variant in result["variants"])
    assert all(variant["train_statistics_eligible"] is False for variant in result["variants"])
