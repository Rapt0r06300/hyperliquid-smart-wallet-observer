from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
from hl_observer.backtesting.copy_vault_causal_selection import (
    confirmed_causal_l2_observation,
)
from hl_observer.backtesting.copy_vault_executable import (
    _observed_book_epoch_rejection,
    causal_book_receipt,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.exec_model import simulate_depth_execution, simulate_execution
from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp
from hl_observer.simulation.cost_components import decompose_execution


def test_pnl_021_execution_uses_observed_exit_touch_not_mid() -> None:
    result = simulate_depth_execution(
        side="SELL",
        notional_usdc=100.0,
        mid_price=100.0,
        bids=[(99.0, 2.0)],
        asks=[(101.0, 2.0)],
    )

    assert result.average_fill_price == 99.0
    assert result.average_fill_price != 100.0
    assert result.reason == "FILLED"


def test_pnl_022_partial_entry_only_closes_the_filled_quantity() -> None:
    entry = simulate_depth_execution(
        side="BUY",
        notional_usdc=150.0,
        mid_price=100.0,
        asks=[(100.0, 1.0)],
        min_fill_ratio=0.0,
    )
    exit_ = simulate_depth_execution(
        side="SELL",
        notional_usdc=entry.filled_notional_usdc,
        mid_price=100.0,
        bids=[(99.0, 1.0)],
        min_fill_ratio=1.0,
    )

    assert entry.partial is True
    assert entry.filled_notional_usdc == 100.0
    assert entry.missed_notional_usdc == 50.0
    assert exit_.requested_notional_usdc == entry.filled_notional_usdc
    assert exit_.requested_notional_usdc != 150.0


def test_pnl_023_favourable_and_adverse_latency_are_signed_and_reconciled() -> None:
    favourable = decompose_execution(
        side="BUY",
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.1,
        mid_at_fill=99.9,
        fee_bps=2.0,
    )
    adverse = decompose_execution(
        side="BUY",
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.1,
        mid_at_fill=100.1,
        fee_bps=2.0,
    )

    assert favourable.latency_bps == -10.0
    assert adverse.latency_bps == 10.0
    assert adverse.total_bps is not None
    assert "total_bps" in favourable.unmeasured
    assert adverse.total_bps > 0.0


def test_pnl_024_stale_taker_book_is_not_served() -> None:
    truth = ExecutionTruth.from_levels(
        coin="BTC",
        bids=[(99.0, 2.0)],
        asks=[(101.0, 2.0)],
        exchange_ts_ms=999,
        received_ts_ms=5_999,
        source="recorded_hyperliquid_l2",
        data_origin="RECORDED_REAL",
    )

    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        execution_truth=truth,
        decision_ts_ms=6_000,
        strict_book=True,
        max_book_age_ms=5_000,
    )

    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.missed_notional_usdc == 100.0
    assert result.reason == "STALE_SOURCE_TIMESTAMP"


def test_pnl_025_gap_stop_uses_observed_mark_not_trigger_price() -> None:
    decision = evaluate_sl_tp(
        side="LONG",
        entry_price=100.0,
        current_price=90.0,
        config=SLTPConfig(stop_loss_bps=50.0, take_profit_bps=500.0),
    )

    assert decision.exit is True
    assert decision.reason == "STOP_LOSS"
    assert decision.pnl_bps == -1_000.0
    assert decision.pnl_bps != -50.0


def test_pnl_026_price_barrier_does_not_infer_liquidation_from_take_profit() -> None:
    take_profit = evaluate_sl_tp(
        side="LONG",
        entry_price=100.0,
        current_price=101.0,
        config=SLTPConfig(stop_loss_bps=50.0, take_profit_bps=100.0),
    )
    ambiguous_without_liquidation_fact = evaluate_sl_tp(
        side="LONG",
        entry_price=100.0,
        current_price=101.0,
        config=SLTPConfig(stop_loss_bps=50.0, take_profit_bps=100.0),
    )

    assert take_profit.reason == "TAKE_PROFIT"
    assert ambiguous_without_liquidation_fact.reason == take_profit.reason
    assert "liquidation" not in ambiguous_without_liquidation_fact.reason.casefold()


def test_pnl_027_rest_backfill_is_audit_only_not_live_causal_evidence(tmp_path) -> None:
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "carnet_venues.jsonl").write_text(
        json.dumps(
            {
                "coin": "BTC",
                "collecte_ts": 1_700_000_000,
                "hl_bid": 99.0,
                "hl_ask": 101.0,
                "taille_min_usd": 1_000.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    books, audit = load_observed_books(tmp_path, coins=["BTC"])

    assert len(books["BTC"]) == 1
    assert books["BTC"][0]["causal_observation"] is False
    assert books["BTC"][0]["source"] == "runtime/data/carnet_venues.jsonl"
    assert audit["source_counts"]["historical_observed"] == 1
    assert audit["causal_forward_rows"] == 0


def test_pnl_028_causal_l2_requires_exchange_and_receive_clocks() -> None:
    row = {
        "source": "HYPERLIQUID_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
        "exchange_ts_ms": 1_000,
        "received_at_ms": 1_005,
        "bids5": [[99.0, 2.0]],
        "asks5": [[101.0, 2.0]],
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
    }

    assert confirmed_causal_l2_observation(row) is True
    assert confirmed_causal_l2_observation({**row, "exchange_ts_ms": None}) is False
    assert confirmed_causal_l2_observation({**row, "received_at_ms": 999}) is False
    assert confirmed_causal_l2_observation({**row, "received_at_ms": True}) is False


def test_pnl_029_same_coin_price_from_another_dex_is_not_causal_hyperliquid_data() -> None:
    row = {
        "source": "DEX_X_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
        "exchange_ts_ms": 1_000,
        "received_at_ms": 1_005,
        "bids5": [[99.0, 2.0]],
        "asks5": [[101.0, 2.0]],
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
    }

    assert confirmed_causal_l2_observation(row) is False


def test_pnl_030_live_heartbeat_does_not_bridge_an_l2_gap_epoch() -> None:
    rows = (
        {"connection_id": "ws-1", "l2_gap_epoch": 7},
        {"connection_id": "ws-1", "l2_gap_epoch": 8},
        {"connection_id": "ws-1", "l2_gap_epoch": 8},
    )

    assert _observed_book_epoch_rejection(rows) == "L2_GAP_EPOCH_CROSSED"
    assert causal_book_receipt(
        book_ts_ms=1_000,
        visible_ts_ms=1_001,
        decision_ts_ms=1_001,
        source_reception_ts_ms=1_000,
    )["status"] == "PROVEN"
