from __future__ import annotations

from hl_observer.copy_wallet.wallet_rank_decay import rank_decay_receipt
from hl_observer.research.wallet_thesis import regime_persistence_receipt
from hl_observer.wallets.discovery_scoring import short_history_receipt
from hl_observer.wallets.per_coin_scoring import normalize_coin_risk_receipt
from hl_observer.wallets.profiler import lookahead_filter_receipt
from hl_observer.wallets.quality_score import survivorship_adjustment
from hl_observer.wallets.scoring import net_fee_score_receipt
from hl_observer.wallets.skill_vs_luck import compare_skill_vs_luck
from hl_observer.wallets.toxicity import jackpot_robustness_receipt
from hl_observer.wallets.wallet_coin_profile import coin_sample_receipt


def test_051_skill_uses_matched_wilson_bounds() -> None:
    result = compare_skill_vs_luck(
        leader_wins=80,
        leader_total=100,
        baseline_wins=55,
        baseline_total=100,
    )
    assert result["status"] == "PROVEN"
    assert result["skill_supported"] is True
    assert result["leader_wilson_lower"] > result["baseline_wilson_lower"]


def test_052_survivorship_requires_delisted_observations() -> None:
    result = survivorship_adjustment(active_count=8, delisted_count=2)
    assert result["status"] == "PROVEN"
    assert result["survivorship_penalty"] == 0.2
    assert survivorship_adjustment(active_count=8, delisted_count=0)["status"] == "MORE_DATA"


def test_053_net_score_deducts_observed_fees() -> None:
    result = net_fee_score_receipt(raw_score=80.0, gross_pnl=100.0, fees=25.0)
    assert result["status"] == "PROVEN"
    assert result["net_pnl"] == 75.0
    assert result["net_score"] == 60.0
    assert result["prioritize_net"] is True


def test_054_coin_sample_stays_unknown_below_minimum() -> None:
    result = coin_sample_receipt(fills_count=2, min_fills=3)
    assert result["status"] == "MORE_DATA"
    assert result["score_known"] is False
    assert coin_sample_receipt(fills_count=3, min_fills=3)["score_known"] is True


def test_055_extreme_jackpot_is_not_robust() -> None:
    result = jackpot_robustness_receipt(top_trade_pnl_share=0.8, leverage=2.0)
    assert result["status"] == "PROVEN"
    assert result["robust"] is False
    assert result["decision"] == "REJECT_EXTREME"


def test_056_rank_decay_records_discovery_delay() -> None:
    result = rank_decay_receipt(base_score=0.8, rank=2, discovery_delay_ms=3_600_000)
    assert result["status"] == "PROVEN"
    assert result["discovery_delay_ms"] == 3_600_000
    assert 0.0 < result["decayed_score"] < 0.8


def test_057_coin_score_is_risk_normalized() -> None:
    result = normalize_coin_risk_receipt(score=80.0, liquidity=50.0, volatility=1.0)
    assert result["status"] == "PROVEN"
    assert result["normalized_score"] == 20.0
    assert result["risk_adjusted"] is True


def test_058_short_history_reduces_confidence() -> None:
    result = short_history_receipt(trades_count=3, estimated_score=90.0, min_trades=30)
    assert result["status"] == "MORE_DATA"
    assert result["adjusted_score"] == 9.0
    assert result["score_known"] is False


def test_059_lookahead_filter_removes_future_fills() -> None:
    result = lookahead_filter_receipt(
        selected_at_ms=100,
        fills=({"time": 90, "id": "old"}, {"time": 110, "id": "future"}),
    )
    assert result["status"] == "PROVEN"
    assert result["observed_count"] == 1
    assert result["post_selection_removed"] == 1
    assert result["lookahead_free"] is True


def test_060_regime_persistence_requires_each_regime() -> None:
    result = regime_persistence_receipt(
        {
            "trend": {"sample_count": 30, "net_pnl_usdc": 4.0},
            "range": {"sample_count": 30, "net_pnl_usdc": 1.0},
        },
        min_samples=30,
    )
    assert result["status"] == "PROVEN"
    assert result["stable_across_regimes"] is True
    assert regime_persistence_receipt({"range": {"sample_count": 2, "net_pnl_usdc": 1.0}})["status"] == "MORE_DATA"
