from __future__ import annotations

from hl_observer.backtesting.copy_vault_executable import cluster_metaorders
from hl_observer.backtesting.copy_vault_protocol import NOTIONAL_USD
from hl_observer.backtesting.copy_vault_v4_train import (
    assess_train_variant,
    explore_copy_vault_v4_train,
    replay_continuation_train,
)


def _live_fill(event_id: str, ts_ms: int, *, action: str) -> dict:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "observed_at_ms": ts_ms + 25,
        "coin": "BTC",
        "direction": 1,
        "action": action,
        "dir": "Open Long",
        "vault": "0xA",
        "taille_usd": 10_000.0,
        "source": "LIVE_WS",
        "is_snapshot": False,
    }


def _book(ts_ms: int, bid: float, ask: float, line: int) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": 10_000.0,
        "source_line": line,
        "causal_observation": True,
    }


def _economic_trade(index: int, net: float, *, vault: str = "0xA") -> dict:
    fees = 0.1
    gross = net + fees
    return {
        "trade_id": f"trade-{index}",
        "vault": vault,
        "coin": "BTC",
        "entry_ts_ms": (20_000 + index // 2) * 86_400_000,
        "exit_ts_ms": (20_000 + index // 2) * 86_400_000 + 1_000,
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net,
        "liquidatable_net": True,
    }


def test_replay_attend_deux_fills_et_utilise_le_notional_fixe() -> None:
    entries = [
        _live_fill("first", 1_000, action="OPEN"),
        _live_fill("second", 2_000, action="ADD"),
    ]
    metaorders, _ = cluster_metaorders(entries)
    signal_ms = 2_025
    books = {
        "BTC": [
            _book(signal_ms, 99.0, 101.0, 1),
            _book(signal_ms + 60_000, 100.0, 102.0, 2),
            _book(signal_ms + 360_000, 109.0, 111.0, 3),
        ]
    }

    trades, audit = replay_continuation_train(
        metaorders,
        books,
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=1_000,
        train_end_ms=10_000,
    )

    assert audit["selection"]["selected_continuations"] == 1
    assert len(trades) == 1
    assert trades[0]["notional_usd"] == NOTIONAL_USD
    assert trades[0]["required_observed_fills"] == 2
    assert trades[0]["causal_forward_eligible"] is True
    assert trades[0]["liquidatable_net"] is True
    assert trades[0]["paper_read_only"] is True
    assert trades[0]["real_execution"] is False


def test_replay_train_refuse_des_bornes_absentes() -> None:
    entries = [
        _live_fill("first", 1_000, action="OPEN"),
        _live_fill("second", 2_000, action="ADD"),
    ]
    metaorders, _ = cluster_metaorders(entries)

    trades, audit = replay_continuation_train(
        metaorders,
        {},
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=None,
        train_end_ms=None,
    )

    assert trades == []
    assert audit["replay"]["INVALID_OR_MISSING_TRAIN_BOUNDS"] == 1


def test_assessment_bloque_un_gain_concentre_sur_un_seul_vault() -> None:
    trades = [_economic_trade(index, 1.0) for index in range(8)]
    placebo = [_economic_trade(index, -0.5, vault="placebo") for index in range(8)]

    result = assess_train_variant(trades, placebo, trial_count=16)

    assert result["statistics"]["net_pnl_usd"] == 8.0
    assert result["economic_summary"]["LIQUIDATABLE_NET"] is True
    assert result["economic_summary"]["economic_reconciliation_ok"] is True
    assert result["placebo_summary"]["net_pnl_usd"] == -4.0
    assert result["eligible"] is False
    assert "VAULT_TRADE_CONCENTRATION_TOO_HIGH" in result["reasons"]


def test_exploration_reste_train_only_et_ne_rejoue_pas_un_petit_echantillon() -> None:
    result = explore_copy_vault_v4_train([], {})

    assert result["heldout_evaluated"] is False
    assert result["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert result["fixed_grid"]["trial_count"] == 16
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert all(
        variant["replay_audit"]["metaorders_considered"] == 0
        for variant in result["variants"]
    )
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
