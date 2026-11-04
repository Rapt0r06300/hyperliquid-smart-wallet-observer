from __future__ import annotations

from hl_observer.backtesting.copy_vault_generalization import long_short_edge_receipt
from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import train_only_markout_receipt
from hl_observer.backtesting.regime_label import regime_ablation_receipt
from hl_observer.copy_wallet.wallet_consensus import dependency_aware_consensus_receipt
from hl_observer.research.exit_factory import blind_exit_ablation_receipt
from hl_observer.research.market_quality import market_quality_veto_receipt
from hl_observer.research.metaorder_hazard import metaorder_aggregation_receipt
from hl_observer.research.wallet_copy_edge import compare_l2_confirmation_receipt
from hl_observer.research.wallet_info_ratio import markout_predictive_value_receipt


def test_151_immediate_and_confirmed_l2_are_paired_on_oos() -> None:
    receipt = compare_l2_confirmation_receipt(
        [
            {"episode_id": "e1", "entry_mode": "IMMEDIATE", "signal_ts_ms": 200, "net_bps": 1.0},
            {"episode_id": "e1", "entry_mode": "L2_CONFIRMED", "signal_ts_ms": 201, "net_bps": 2.0},
        ],
        cutoff_ms=100,
    )
    assert receipt["status"] == "COMPARABLE"
    assert receipt["paired_oos_episodes"] == 1


def test_152_markout_filter_is_frozen_from_train_only() -> None:
    train = [
        {"leader_id": "w", "entry_ts_ms": 100, "markout_observed_at_ms": 110, "markout_bps": 2.0},
        {"leader_id": "w", "entry_ts_ms": 200, "markout_observed_at_ms": 210, "markout_bps": 3.0},
    ]
    receipt = train_only_markout_receipt(
        train,
        [{"leader_id": "w", "entry_ts_ms": 300, "future_markout_bps": 999.0}],
        cutoff_ms=250,
        min_history=1,
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["candidate_future_markout_ignored"] is True


def test_153_exit_ablation_uses_identical_paths_and_costs() -> None:
    receipt = blind_exit_ablation_receipt(
        [[0.0, 2.0, 4.0], [0.0, 1.0, 3.0]],
        regle_autonome="HORIZON_FIXE",
        regle_aveugle="TIME_STOP",
        cost_bps=1.0,
        risk_penalty_bps=0.5,
    )
    assert receipt["verdict"] == "PROVEN"
    assert receipt["same_costs"] is True


def test_154_metaorder_aggregation_matches_weighted_fills() -> None:
    receipt = metaorder_aggregation_receipt(
        [{"metaorder_id": "m1", "net_pnl_bps": 3.0}],
        [
            {"metaorder_id": "m1", "net_pnl_bps": 2.0, "notional_usd": 1.0},
            {"metaorder_id": "m1", "net_pnl_bps": 4.0, "notional_usd": 1.0},
        ],
    )
    assert receipt["verdict"] == "PROVEN"
    assert receipt["all_matched"] is True


def test_155_dependent_wallets_do_not_form_strict_consensus() -> None:
    receipt = dependency_aware_consensus_receipt(
        [{"adresse": "w1", "coin": "BTC", "side": "BUY", "ts_ms": 100, "size": 1.0}],
        as_of_ms=200,
    )
    assert receipt["status"] == "UNMEASURABLE"


def test_156_regime_allowlist_is_frozen_on_train_then_applied_oos() -> None:
    train = [{"regime": "HIGH", "gross_pnl_bps": 3.0, "cost_bps": 1.0}] * 3
    receipt = regime_ablation_receipt(
        train,
        [{"regime": "HIGH", "gross_pnl_bps": 2.0, "cost_bps": 1.0}],
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["selection_scope"] == "TRAIN_ONLY_COSTED"


def test_157_market_quality_veto_compares_same_oos_fields() -> None:
    row = {
        "episode_id": "e1", "trial_id": "t1", "opened_at_ms": 100,
        "book_ts_ms": 99, "spread_bps": 2.0, "depth_usd": 2_000.0,
        "gross_pnl_bps": 3.0, "cost_bps": 1.0,
    }
    receipt = market_quality_veto_receipt([row], [{**row, "opened_at_ms": 200, "book_ts_ms": 199}], cutoff_ms=150)
    assert receipt["verdict"] == "PROVEN"
    assert receipt["causal_veto_required"] is True


def test_158_long_short_edge_keeps_funding_and_costs_separate() -> None:
    base = {
        "gross_edge_bps": 5.0, "fees_bps": 1.0, "spread_bps": 1.0,
        "slippage_bps": 0.5, "latency_bps": 0.5, "funding_bps": 0.2,
    }
    train = [
        {**base, "direction": "LONG", "episode_id": "tl", "signal_ts_ms": 100},
        {**base, "direction": "SHORT", "episode_id": "ts", "signal_ts_ms": 101},
    ]
    oos = [
        {**base, "direction": "LONG", "episode_id": "ol", "signal_ts_ms": 200},
        {**base, "direction": "SHORT", "episode_id": "os", "signal_ts_ms": 201},
    ]
    receipt = long_short_edge_receipt(train, oos, cutoff_ms=150, min_oos_trades_per_side=1)
    assert receipt["verdict"] == "PROVEN"
    assert receipt["both_directions_costed"] is True


def test_159_markout_predictive_value_uses_same_frozen_oos_outcomes() -> None:
    train = [
        {"episode_id": "t1", "signal_ts_ms": 100, "leader_markout_score_bps": 1.0, "pnl_score_bps": 1.0, "realized_net_pnl_bps": 1.0},
        {"episode_id": "t2", "signal_ts_ms": 101, "leader_markout_score_bps": 3.0, "pnl_score_bps": 3.0, "realized_net_pnl_bps": 3.0},
    ]
    oos = [
        {"episode_id": "o1", "signal_ts_ms": 200, "leader_markout_score_bps": 1.0, "pnl_score_bps": 1.0, "realized_net_pnl_bps": 2.0},
        {"episode_id": "o2", "signal_ts_ms": 201, "leader_markout_score_bps": 3.0, "pnl_score_bps": 3.0, "realized_net_pnl_bps": 4.0},
    ]
    receipt = markout_predictive_value_receipt(train, oos, cutoff_ms=150, min_rows_per_bucket=1)
    assert receipt["verdict"] == "PROVEN"
    assert receipt["same_oos_outcome"] is True
