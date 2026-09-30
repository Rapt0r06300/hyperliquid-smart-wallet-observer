"""Câblage: qualité wallet dans le pipeline leaders + APR/rotation funding."""

from __future__ import annotations

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre import
from hl_observer.integration.funding_arb_optimizer import (
    optimize_funding_positions, rank_funding_candidates_by_apr,
)
from hl_observer.integration.leader_pipeline import refine_shortlist_with_quality


def test_quality_refinement_off_keeps_base_order(monkeypatch):
    monkeypatch.delenv("HYPERSMART_WALLET_QUALITY_SCORING", raising=False)
    out = refine_shortlist_with_quality(candidate_wallets=["a", "b"], quality_inputs={}, base_scores={"a": 60, "b": 80})
    assert out["applied"] is False and out["ranked"] == ["b", "a"]


def test_quality_refinement_promotes_consistent_demotes_lucky(monkeypatch):
    monkeypatch.setenv("HYPERSMART_WALLET_QUALITY_SCORING", "1")
    qin = {
        "consistent": {"pnl_7d": 50, "pnl_30d": 200, "pnl_90d": 600, "max_drawdown_pct": 12, "profit_factor": 2.2, "behavior_kind": "SWING"},
        "lucky": {"pnl_7d": -10, "pnl_30d": -30, "pnl_90d": 5000, "max_drawdown_pct": 55, "profit_factor": 1.1, "largest_trade_pnl": 5200, "total_gross_profit": 5300},
    }
    # base: lucky score plus haut au départ
    out = refine_shortlist_with_quality(candidate_wallets=["consistent", "lucky"], quality_inputs=qin, base_scores={"consistent": 70, "lucky": 78})
    assert out["applied"] is True
    assert out["ranked"][0] == "consistent"   # la qualité renverse le classement
    assert out["refined_scores"]["lucky"] < out["refined_scores"]["consistent"]


def test_funding_apr_rotation_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_FUNDING_ARB_APR_ROTATION", raising=False)
    out = optimize_funding_positions(current_coin=None, current_rate_bps_per_hour=None, candidate_rates={"HYPE": 3.0})
    assert out["applied"] is False and out["decision"] == "PASSTHROUGH"


def test_funding_apr_rotation_and_rebalance(monkeypatch):
    monkeypatch.setenv("HYPERSMART_FUNDING_ARB_APR_ROTATION", "1")
    # position décroît + meilleure alternative -> rotation
    rot = optimize_funding_positions(current_coin="HYPE", current_rate_bps_per_hour=0.02, candidate_rates={"HYPE": 0.02, "BTC": 3.0})
    assert rot["decision"] == "ROTATE" and rot["to_coin"] == "BTC"
    # position tient mais jambes divergent -> rebalance
    reb = optimize_funding_positions(current_coin="HYPE", current_rate_bps_per_hour=3.0, candidate_rates={"HYPE": 3.0}, long_leg_usdt=100, short_leg_usdt=88)
    assert reb["decision"] == "REBALANCE"


def test_rank_candidates_by_apr_filters_gate():
    rows = rank_funding_candidates_by_apr({"HYPE": 3.0, "DUST": 0.02}, min_apr_pct=5.0)
    coins = [r["coin"] for r in rows]
    assert "HYPE" in coins and "DUST" not in coins   # DUST sous le gate APR
