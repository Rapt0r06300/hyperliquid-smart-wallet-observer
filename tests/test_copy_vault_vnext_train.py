from __future__ import annotations

from hl_observer.backtesting.copy_vault_vnext_train import (
    admit_consensus_train_rows,
    explore_copy_vault_vnext_train,
)


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
    assert result["freeze_candidate"]["identity_claim"].startswith("ENTITY_NORMALIZED")


def test_copy_vnext_refuse_de_selectionner_avant_freeze_physique_de_base() -> None:
    day = 86_400_000
    result = explore_copy_vault_vnext_train(
        {
            "provisional_without_physical_freeze": True,
            "trades": [
                _row(
                    ts=1_800_000_000_000 + day_index * day + wallet_index * 1_000,
                    vault=f"0x{wallet_index}",
                    coin="ETH" if day_index % 2 == 0 else "SOL",
                )
                for day_index in range(4)
                for wallet_index in range(3)
            ],
        }
    )
    assert result["status"] == "BASE_COPY_PARAMETERS_NOT_PHYSICALLY_FROZEN"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["freeze_candidate"] is None
    assert result["diagnostic_only"] is True
    assert result["diagnostic_not_admitted_pnl"] is True
    assert result["train_rows_seen"] == 12
    assert result["diagnostic_train_candidate_count"] >= 1
    assert result["diagnostic_train_candidate"]["statistics"]["net_pnl_usd"] > 0
    assert all(variant["eligible"] is False for variant in result["variants"])


def test_copy_vnext_fail_closed_when_execution_capacity_is_missing() -> None:
    day = 86_400_000
    rows: list[dict] = []
    for day_index in range(4):
        base = (30_000 + day_index) * day
        coin = "ETH" if day_index % 2 == 0 else "SOL"
        for wallet_index in range(3):
            rows.append(
                _row(
                    ts=base + (wallet_index + 1) * 1_000,
                    vault=f"0x{wallet_index}",
                    coin=coin,
                )
            )
    rows[0].pop("entry_capacity_usd")

    result = explore_copy_vault_vnext_train(
        {"provisional_without_physical_freeze": False, "trades": rows}
    )

    assert result["train_rows_seen"] == 11


def test_copy_vnext_fail_closed_when_execution_evidence_is_incomplete() -> None:
    required_fields = (
        "entry_price",
        "exit_price",
        "notional_usd",
        "entry_capacity_usd",
        "exit_capacity_usd",
        "reference_lag_ms",
        "entry_target_lag_ms",
        "exit_target_lag_ms",
        "observed_latency_ms",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
    )
    for index, field in enumerate(required_fields):
        row = _row(ts=1_900_000_000_000 + index, vault=f"0x{index}")
        row.pop(field)
        result = explore_copy_vault_vnext_train(
            {"provisional_without_physical_freeze": False, "trades": [row]}
        )
        assert result["train_rows_seen"] == 0, field


def test_copy_vnext_refuses_capacity_below_notional() -> None:
    row = _row(ts=1_900_100_000_000, vault="0xcapacity")
    row["entry_capacity_usd"] = row["notional_usd"] - 0.01

    result = explore_copy_vault_vnext_train(
        {"provisional_without_physical_freeze": False, "trades": [row]}
    )

    assert result["train_rows_seen"] == 0


def test_copy_vnext_does_not_count_same_public_entity_as_independent_wallets() -> None:
    rows = [
        {
            **_row(ts=2_000_000_000_000 + index * 1_000, vault=f"0x{index}"),
            "public_entity_id": "public-entity-one",
        }
        for index in range(3)
    ]

    admitted, reasons = admit_consensus_train_rows(
        rows,
        window_ms=30_000,
        minimum_distinct_wallets=2,
    )

    assert admitted == []
    assert reasons["ENTITY_INDEPENDENCE_NOT_PROVEN"] >= 1
