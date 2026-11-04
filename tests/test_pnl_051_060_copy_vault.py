from __future__ import annotations

from hl_observer.backtesting.copy_vault_accounting_controls import (
    unrealized_liquidable_receipt,
)
from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_executable import (
    execute_metaorder,
    replay_metaorders,
)
from hl_observer.backtesting.copy_vault_scientific_controls import (
    dataset_cutoff_receipt,
    forward_freeze_receipt,
    observed_liquidation_receipt,
    oos_retuning_revocation_receipt,
)
from hl_observer.copying.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitState,
    evaluate_circuit_breaker,
    record_trade_result,
)
from hl_observer.simulation.capital_accounting import (
    CapitalAccountingTracker,
    PositionCapitalInput,
)
from hl_observer.simulation.copy_cost_adapter import measure_copy_cost_components
from hl_observer.simulation.fee_model import compute_fee_usdc
from hl_observer.simulation.pnl_attribution import partial_close_fee_receipt


def _entry(
    event_id: str,
    ts_ms: int,
    *,
    coin: str = "BTC",
    vault: str = "0xA",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "coin": coin,
        "direction": 1,
        "action": "OPEN",
        "dir": "Open Long",
        "vault": vault,
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }


def _book(ts_ms: int, bid: float, ask: float) -> dict[str, object]:
    capacity = 1_000.0
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": capacity,
        "bids5": [[bid, capacity / bid]],
        "asks5": [[ask, capacity / ask]],
        "source_line": 1,
        "causal_observation": False,
    }


def test_pnl051_heldout_retuning_is_revoked_instead_of_certified() -> None:
    clean = oos_retuning_revocation_receipt([{"episode_id": "e-1", "used_for_tuning": False}])
    reused = oos_retuning_revocation_receipt([{"episode_id": "e-2", "retuned_on_heldout": True}])

    assert clean["status"] == "PROVEN"
    assert reused["status"] == "REJECTED"
    assert reused["verdict"] == "OOS_RETUNING_DETECTED"


def test_pnl052_feature_training_cutoff_requires_train_only_rows() -> None:
    manifest = "a" * 64
    clean = dataset_cutoff_receipt(
        [{"source_ts_ms": 100, "manifest_hash": manifest}],
        oos_start_ms=200,
        manifest_hash=manifest,
    )
    violation = dataset_cutoff_receipt(
        [{"source_ts_ms": 200, "manifest_hash": manifest}],
        oos_start_ms=200,
        manifest_hash=manifest,
    )

    assert clean["status"] == "PROVEN"
    assert violation["status"] == "REJECTED"


def test_pnl053_three_losses_pause_sizing_fail_closed() -> None:
    state = CircuitBreakerState()
    config = CircuitBreakerConfig(pause_losing_streak=3, halt_losing_streak=6)
    for _ in range(3):
        record_trade_result(state, pnl_bps=-1.0, pnl_usdt=-0.1)

    evaluated = evaluate_circuit_breaker(state, config)

    assert evaluated.state == CircuitState.PAUSED
    assert evaluated.sizing_multiplier == 0.0
    assert "PAUSE_LOSING_STREAK_3" in evaluated.reasons


def test_pnl054_simultaneous_positions_sum_margin_and_liquidable_pnl() -> None:
    tracker = CapitalAccountingTracker(starting_equity_usd=200.0)
    snapshot = tracker.observe(
        collateral_cash_usd=200.0,
        positions=(
            PositionCapitalInput("p1", (40.0,), (1,), 2.0, -2.0, -2.5),
            PositionCapitalInput("p2", (20.0,), (-1,), 2.0, -1.0, -1.5),
        ),
        realized_pnl_usd=0.0,
        turnover_usd=60.0,
    )

    assert snapshot.margin_locked_usd == 30.0
    assert snapshot.gross_exposure_usd == 60.0
    assert snapshot.liquidatable_pnl_usd == -4.0
    assert snapshot.liquidatable_equity_usd == 196.0


def test_pnl055_multiple_leaders_same_coin_keep_distinct_metaorders() -> None:
    metaorders, audit = cluster_metaorders([
        _entry("leader-a", 1_000),
        _entry("leader-b", 400_000, coin="BTC", vault="0xB"),
    ])
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
        _book(400_000, 99.0, 101.0),
        _book(460_000, 100.0, 102.0),
        _book(760_000, 109.0, 111.0),
    ]

    trades, diagnostics = replay_metaorders(metaorders, {"BTC": books}, horizon_ms=300_000)

    assert audit["invalid_events_rejected"] == 0
    assert diagnostics["completed_positions"] == 2
    assert len({trade["trade_id"] for trade in trades}) == 2


def test_pnl056_missing_l2_refuses_emergency_exit_without_imputation() -> None:
    metaorder = cluster_metaorders([_entry("no-book", 1_000)])[0][0]

    trade, reason = execute_metaorder(metaorder, [], horizon_ms=300_000)

    assert trade is None
    assert reason == "NO_OBSERVED_BOOK_FOR_COIN"


def test_pnl057_capacity_spread_latency_stress_is_incomplete_without_depth() -> None:
    receipt = measure_copy_cost_components(
        [{"coin": "BTC", "ts_ms": 1_000, "move_frac": 0.02}],
        {"BTC": []},
        notional_usd=200.0,
        copy_delay_ms=60_000.0,
        horizon_ms=300_000.0,
        threshold=0.01,
    )

    assert receipt["complete"] is False
    assert receipt["components_bps"] is None
    assert receipt["failure_counts"] == {"DEPTH_MISSING": 1}


def test_pnl058_favorable_liquidation_requires_observed_book_mark() -> None:
    receipt = observed_liquidation_receipt([
        {
            "observed_liquidation_price": 105.0,
            "quantity": 1.0,
            "book_observed": True,
        }
    ])

    assert receipt["status"] == "PROVEN"
    assert unrealized_liquidable_receipt(
        {"unrealized_pnl_usd": 5.0, "liquidable_value_usd": 104.9, "book_observed": True}
    )["status"] == "PROVEN"


def test_pnl059_partial_liquidation_preserves_residual_margin_quantity() -> None:
    receipt = partial_close_fee_receipt(
        [{"quantity": 1.0, "fee_usdc": 0.02}, {"quantity": 0.5, "fee_usdc": 0.01}],
        residual_quantity=0.5,
    )

    assert receipt["status"] == "PROVEN"
    assert receipt["closed_quantity"] == 1.5
    assert receipt["residual_quantity"] == 0.5
    assert receipt["residual_preserved"] is True


def test_pnl060_fixed_fees_are_nonzero_on_200_usd_paper_capital() -> None:
    fee = compute_fee_usdc(200.0, 9.0)

    assert fee == 0.18
    assert fee > 0.0

