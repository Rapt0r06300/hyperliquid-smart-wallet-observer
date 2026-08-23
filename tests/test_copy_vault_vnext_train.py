from __future__ import annotations

from hl_observer.backtesting.copy_vault_vnext_train import explore_copy_vault_vnext_train


def _row(
    *, ts: int, vault: str, coin: str = "ETH", segment: str = "train", net: float = 1.0
) -> dict:
    return {
        "trade_id": f"{segment}-{vault}-{coin}-{ts}",
        "vault": vault,
        "coin": coin,
        "direction": 1,
        "signal_ts_ms": ts,
        "walk_forward_segment": segment,
        "liquidatable_net": True,
        "gross_pnl_usd": net,
        "fees_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net,
    }


def test_copy_vnext_selection_ignore_totalement_oos_et_exige_consensus_prior_only() -> None:
    day = 86_400_000
    rows: list[dict] = []
    for day_index in range(4):
        base = (20_000 + day_index) * day
        coin = "ETH" if day_index % 2 == 0 else "SOL"
        rows.extend(
            [
                _row(ts=base + 1_000, vault="0xa", coin=coin),
                _row(ts=base + 2_000, vault="0xb", coin=coin),
                _row(ts=base + 3_000, vault="0xc", coin=coin),
            ]
        )
    # A gigantic heldout winner must not alter TRAIN selection or its net.
    rows.append(
        _row(
            ts=99_999 * day,
            vault="0xdead",
            coin="BTC",
            segment="oos",
            net=1_000_000.0,
        )
    )
    report = {
        "provisional_without_physical_freeze": False,
        "trades": rows,
    }

    result = explore_copy_vault_vnext_train(report)

    assert result["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert result["heldout_evaluated"] is False
    assert result["train_rows_seen"] == 12
    assert result["selection_eligible"] is True
    assert result["selected"]["statistics"]["net_pnl_usd"] == 8.0
    assert result["selected"]["largest_coin_trade_share"] == 0.5
    assert result["freeze_candidate"]["identity_claim"].startswith("DISTINCT_RECORDED_WALLET")


def test_copy_vnext_refuse_de_selectionner_avant_freeze_physique_de_base() -> None:
    result = explore_copy_vault_vnext_train(
        {"provisional_without_physical_freeze": True, "trades": []}
    )
    assert result["status"] == "BASE_COPY_PARAMETERS_NOT_PHYSICALLY_FROZEN"
    assert result["selection_eligible"] is False
