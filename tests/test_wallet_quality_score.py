"""SCAN-QUALITY: couche qualité wallet (anti-lucky, consistance, comportement)."""

from __future__ import annotations

from hl_observer.wallets.quality_score import (
    compute_wallet_quality, quality_scoring_enabled, refine_discovery_score,
)


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_WALLET_QUALITY_SCORING", raising=False)
    assert quality_scoring_enabled() is False


def test_consistent_swing_trader_boosted():
    q = compute_wallet_quality(pnl_7d=50, pnl_30d=200, pnl_90d=600, max_drawdown_pct=12,
                               profit_factor=2.2, largest_trade_pnl=100, total_gross_profit=1000, behavior_kind="SWING")
    assert q.multiplier > 1.0                       # bon profil -> boost
    assert "CONSISTENT_ALL_WINDOWS" in q.reasons and "SWING_COPYABLE" in q.reasons
    assert refine_discovery_score(70.0, q) > 70.0


def test_lucky_trader_one_big_win_penalized():
    q = compute_wallet_quality(pnl_7d=-10, pnl_30d=-30, pnl_90d=5000, max_drawdown_pct=55,
                               profit_factor=1.1, largest_trade_pnl=5200, total_gross_profit=5300)
    assert "SINGLE_TRADE_CONCENTRATION" in q.reasons  # profit = un seul coup
    assert q.multiplier < 0.7                          # fortement pénalisé
    assert refine_discovery_score(80.0, q) < 80.0


def test_scalper_downweighted_even_if_profitable():
    q = compute_wallet_quality(pnl_7d=100, pnl_30d=300, pnl_90d=900, max_drawdown_pct=10,
                               profit_factor=2.0, largest_trade_pnl=50, total_gross_profit=1000, behavior_kind="SCALPER")
    assert q.behavior_factor < 0.5                     # non copiable via latence
    assert any("UNCOPYABLE" in r for r in q.reasons)


def test_unknown_metrics_stay_neutral():
    q = compute_wallet_quality()                        # rien de connu
    assert 0.5 <= q.multiplier <= 1.0                   # neutre, jamais inventé
    assert "WINDOWS_UNKNOWN" in q.reasons


def test_high_churn_penalized():
    q = compute_wallet_quality(pnl_7d=100, pnl_30d=300, pnl_90d=900, max_drawdown_pct=10,
                               profit_factor=2.0, behavior_kind="SWING", trade_switch_rate_per_day=80)
    assert "HIGH_TRADE_CHURN" in q.reasons
