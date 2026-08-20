from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.economic_hypotheses_v3 import (
    qualify_copy_vault_train_only,
    qualify_cross_venue_train_only,
    qualify_lead_lag_queue_maker_train_only,
)


def _copy_trade(
    *,
    vault: str = "0xleader",
    coin: str = "BTC",
    net: float = 0.20,
    segment: str = "train",
) -> dict:
    fees = 0.02
    spread = 0.01
    return {
        "vault": vault,
        "coin": coin,
        "walk_forward_segment": segment,
        "gross_pnl_usd": net + fees + spread,
        "fees_usd": fees,
        "spread_cost_usd": spread,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net,
        "liquidatable_net": True,
    }


def _robust_copy_train() -> list[dict]:
    values = [0.20, 0.20, 0.20, 0.20, 0.20, 0.20, 0.20, -0.10]
    return [
        _copy_trade(coin="BTC" if index % 2 == 0 else "ETH", net=net)
        for index, net in enumerate(values)
    ]


def test_copy_v3_selection_is_train_only() -> None:
    train = _robust_copy_train()
    baseline = qualify_copy_vault_train_only(train)
    contaminated = train + [
        _copy_trade(
            vault="0xooswinner",
            coin="SOL",
            net=10_000.0,
            segment="oos",
        )
        for _ in range(20)
    ]
    after = qualify_copy_vault_train_only(contaminated)

    assert baseline["status"] == "TRAIN_ELIGIBLE"
    assert baseline["selected"]["vault"] == "0xleader"
    assert after["selected"] == baseline["selected"]
    assert after["selection_evidence_sha256"] == baseline["selection_evidence_sha256"]
    assert after["non_train_rows_ignored"] == 20


def test_copy_v3_rejects_concentration_and_negative_sufficient_sample() -> None:
    concentrated = [_copy_trade(coin="BTC", net=0.20) for _ in range(8)]
    result = qualify_copy_vault_train_only(concentrated)
    assert result["selection_eligible"] is False
    assert "TRAIN_COIN_CONCENTRATION_TOO_HIGH" in result["candidates"][0]["reasons"]

    negative = [
        _copy_trade(coin="BTC" if index % 2 == 0 else "ETH", net=-0.10)
        for index in range(8)
    ]
    result = qualify_copy_vault_train_only(negative)
    assert result["status"] == "KILL_TRAIN_NO_ROBUST_LEADER"
    assert result["physical_freeze_allowed"] is False


def _maker_candidate(*, net: float, segment: str = "train", queue: bool = True) -> dict:
    fees = 0.01
    row = {
        "coin": "ETH",
        "segment": segment,
        "lead_shock_bps": 25.0,
        "gross_pnl_usd": net + fees,
        "fees_usd": fees,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net,
        "liquidatable_net": True,
    }
    if queue:
        row.update(
            {
                "initial_qty_ahead": 1.0,
                "paper_order_qty": 0.25,
                "required_qty_for_full_fill": 1.25,
                "queue_events": [
                    {"book_size_change": -0.6, "traded_qty_at_level": 0.6},
                    {"book_size_change": -0.7, "traded_qty_at_level": 0.7},
                ],
            }
        )
    return row


def test_lead_lag_v3_refuses_touch_only_maker_fill() -> None:
    report = {
        "maker_queue_candidates": [
            _maker_candidate(net=2.0, queue=False) for _ in range(20)
        ]
    }
    result = qualify_lead_lag_queue_maker_train_only(report)
    assert result["status"] == "MORE_DATA_QUEUE_EVIDENCE_REQUIRED"
    assert result["queue_proven_fills"] == 0
    assert result["selection_eligible"] is False


def test_lead_lag_v3_accepts_only_queue_proven_profitable_train() -> None:
    candidates = [
        _maker_candidate(net=0.20 if index < 7 else -0.10)
        for index in range(8)
    ]
    candidates.extend(
        _maker_candidate(net=-100.0, segment="oos") for _ in range(10)
    )
    result = qualify_lead_lag_queue_maker_train_only(
        {
            "maker_queue_candidates": candidates,
            "maker_queue_replay": {
                "latency_measured": True,
                "strong_shocks_seen": 8,
                "train_placebo_net_pnl_usd": 0.5,
            },
        }
    )
    assert result["status"] == "TRAIN_ELIGIBLE"
    assert result["queue_proven_fills"] == 8
    assert result["non_train_rows_ignored"] == 10
    assert result["train_net_pnl_usd"] == 1.3
    assert result["beats_train_placebo"] is True


def test_lead_lag_v3_refuses_profitable_train_when_placebo_is_better() -> None:
    candidates = [
        _maker_candidate(net=0.20 if index < 7 else -0.10)
        for index in range(8)
    ]
    result = qualify_lead_lag_queue_maker_train_only(
        {
            "maker_queue_candidates": candidates,
            "maker_queue_replay": {
                "latency_measured": True,
                "strong_shocks_seen": 8,
                "train_placebo_net_pnl_usd": 2.0,
            },
        }
    )

    assert result["status"] == "KILL_TRAIN_PLACEBO_NOT_BEATEN"
    assert result["selection_eligible"] is False
    assert result["beats_train_placebo"] is False


def test_lead_lag_v3_does_not_fill_when_only_queue_ahead_is_consumed() -> None:
    candidate = _maker_candidate(net=2.0)
    candidate["queue_events"] = [
        {"book_size_change": -0.6, "traded_qty_at_level": 0.6},
        {"book_size_change": -0.5, "traded_qty_at_level": 0.5},
    ]
    result = qualify_lead_lag_queue_maker_train_only(
        {"maker_queue_candidates": [candidate]}
    )
    assert result["queue_proven_fills"] == 0
    assert result["selection_eligible"] is False


def _cross_trade(
    *,
    coin: str = "ETH",
    net_bps: float = 20.0,
    segment: str = "train",
) -> dict:
    notional = 15.0
    return {
        "coin": coin,
        "walk_forward_segment": segment,
        "two_leg": True,
        "LIQUIDATABLE_NET": True,
        "depth_freshness_ms": 100.0,
        "basis_detect_bps": 40.0,
        "basis_in_bps": 35.0,
        "basis_out_bps": 5.0,
        "notional_usd": notional,
        "net_bps": net_bps,
        "net_usd": notional * net_bps / 10_000.0,
    }


def _robust_cross_train() -> list[dict]:
    return [
        _cross_trade(net_bps=20.0 if index < 7 else -10.0)
        for index in range(8)
    ]


def test_cross_v3_selection_is_train_only() -> None:
    train = _robust_cross_train()
    baseline = qualify_cross_venue_train_only(
        train,
        source_mode="ATOMIC_FOUR_SIDE_BOOK",
    )
    changed = deepcopy(train)
    changed.extend(_cross_trade(coin="SAGA", net_bps=50_000.0, segment="oos") for _ in range(20))
    after = qualify_cross_venue_train_only(
        changed,
        source_mode="ATOMIC_FOUR_SIDE_BOOK",
    )
    assert baseline["status"] == "TRAIN_ELIGIBLE"
    assert after["selected"] == baseline["selected"]
    assert after["selection_evidence_sha256"] == baseline["selection_evidence_sha256"]
    assert after["non_train_rows_ignored"] == 20


def test_cross_v3_requires_atomic_four_side_source() -> None:
    result = qualify_cross_venue_train_only(
        _robust_cross_train(),
        source_mode="RECONSTRUCTED_BBO",
    )
    assert result["status"] == "MORE_DATA_ATOMIC_FOUR_SIDE_BOOK_REQUIRED"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
