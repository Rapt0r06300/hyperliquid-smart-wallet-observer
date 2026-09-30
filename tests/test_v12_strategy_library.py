"""Tests des 15 stratégies paper V10.7 (#120/#121/#122) — pures, deny-by-default, sim-only."""

import pytest

from hl_observer.strategies import PaperStrategyRegistry, approve_with_risk, is_actionable
from hl_observer.strategies.models import IntentAction, IntentSide, PaperIntent
from hl_observer.strategies import library as L
from hl_observer.storage.run_context import RunContext


# ---- Lot 1 ----
def test_fade_vs_follow_impulse_opposite_sides():
    fade = L.FadeImpulseStrategy.default().propose(coin="BTC", impulse_bps=60, now_ms=1)
    follow = L.FollowImpulseStrategy.default().propose(coin="BTC", impulse_bps=60, now_ms=1)
    assert fade.side is IntentSide.SHORT and follow.side is IntentSide.LONG
    assert L.FadeImpulseStrategy.default().propose(coin="BTC", impulse_bps=5, now_ms=1) is None


def test_whale_fill_early():
    s = L.WhaleFillEarlyStrategy.default()
    assert s.propose(coin="ETH", leader_side=IntentSide.LONG, leader_notional_usdc=10_000, signal_age_ms=1000) is None  # too small
    assert s.propose(coin="ETH", leader_side=IntentSide.LONG, leader_notional_usdc=500_000, signal_age_ms=999_999) is None  # stale
    ok = s.propose(coin="ETH", leader_side=IntentSide.LONG, leader_notional_usdc=500_000, signal_age_ms=2000, now_ms=1)
    assert ok is not None and ok.side is IntentSide.LONG


def test_direction_multi_tf_agreement():
    s = L.DirectionMultiTfStrategy.default()
    assert s.propose(coin="BTC", dir_5m=IntentSide.LONG, dir_15m=IntentSide.LONG, dir_1h=IntentSide.LONG, now_ms=1).side is IntentSide.LONG
    assert s.propose(coin="BTC", dir_5m=IntentSide.LONG, dir_15m=IntentSide.SHORT, dir_1h=IntentSide.LONG, now_ms=1) is None


# ---- Lot 2 ----
def test_mean_reversion_and_momentum():
    assert L.MeanReversionStrategy.default().propose(coin="BTC", deviation_bps=40, now_ms=1).side is IntentSide.SHORT
    assert L.MomentumStrategy.default().propose(coin="BTC", return_bps=40, now_ms=1).side is IntentSide.LONG


def test_spread_farm_needs_spread_and_imbalance():
    s = L.SpreadFarmStrategy.default()
    assert s.propose(coin="BTC", spread_bps=4, imbalance=0.3, now_ms=1) is None  # spread too tight
    assert s.propose(coin="BTC", spread_bps=12, imbalance=0.3, now_ms=1).side is IntentSide.LONG


def test_volatility_breakout_and_low_vol_scalping():
    vb = L.VolatilityBreakoutStrategy.default()
    assert vb.propose(coin="BTC", breakout_bps=60, vol_expanding=False, now_ms=1) is None
    assert vb.propose(coin="BTC", breakout_bps=60, vol_expanding=True, now_ms=1).side is IntentSide.LONG
    lv = L.LowVolScalpingStrategy.default()
    assert lv.propose(coin="BTC", volatility_bps=30, imbalance=0.3, spread_bps=2, now_ms=1) is None  # too volatile
    assert lv.propose(coin="BTC", volatility_bps=5, imbalance=0.3, spread_bps=2, now_ms=1).side is IntentSide.LONG


# ---- Lot 3 ----
def test_cross_source_discrepancy():
    s = L.CrossSourceDiscrepancyStrategy.default()
    assert s.propose(coin="BTC", price_index=100.0, price_venue=100.01, now_ms=1) is None  # dev ~1 bps < 8
    assert s.propose(coin="BTC", price_index=100.0, price_venue=200.0, now_ms=1) is None  # dev huge -> bad data
    ok = s.propose(coin="BTC", price_index=100.0, price_venue=99.7, now_ms=1)  # ~30 bps, venue below
    assert ok is not None and ok.side is IntentSide.LONG


def test_dca_sim():
    s = L.DcaSimStrategy.default()
    assert s.propose(coin="BTC", base_side=IntentSide.LONG, elapsed_since_last_ms=1000, legs_done=0, now_ms=1) is None  # too soon
    ok = s.propose(coin="BTC", base_side=IntentSide.LONG, elapsed_since_last_ms=4_000_000, legs_done=1, now_ms=1)
    assert ok is not None and ok.action is IntentAction.ADD


def test_kelly_sizing():
    s = L.KellySizingStrategy.default()
    assert s.propose(coin="BTC", side=IntentSide.LONG, win_prob=0.4, win_loss_ratio=1.0, equity_usdt=1000, now_ms=1) is None  # no edge
    ok = s.propose(coin="BTC", side=IntentSide.LONG, win_prob=0.7, win_loss_ratio=2.0, equity_usdt=1000, now_ms=1)
    assert ok is not None and ok.target_notional_usdt == 100.0  # capped at 10% of 1000


def test_strategy_ensemble_consensus():
    s = L.StrategyEnsembleStrategy.default()
    longs = [L.MomentumStrategy.default().propose(coin="BTC", return_bps=40, now_ms=1),
             L.FollowImpulseStrategy.default().propose(coin="BTC", impulse_bps=60, now_ms=1)]
    assert s.propose(coin="BTC", intents=longs[:1], now_ms=1) is None  # < min_agree
    cons = s.propose(coin="BTC", intents=longs, now_ms=1)
    assert cons is not None and cons.side is IntentSide.LONG


def test_shadow_model_is_flagged_and_rag_never_trades():
    sh = L.ShadowModelStrategy.default().propose(coin="BTC", side=IntentSide.LONG, now_ms=1)
    assert sh is not None and L.is_shadow(sh) and L.SHADOW_REASON in sh.reasons
    rag = L.RagEvidenceContextStrategy.default()
    assert rag.propose(coin="BTC") is None  # context only
    assert rag.evidence(refs=["a", "b"]) == ("a", "b")


# ---- invariants + registry ----
def test_all_intents_are_simulation_only_and_not_actionable():
    intents = [
        L.FadeImpulseStrategy.default().propose(coin="BTC", impulse_bps=60, now_ms=1),
        L.KellySizingStrategy.default().propose(coin="BTC", side=IntentSide.LONG, win_prob=0.7, win_loss_ratio=2.0, equity_usdt=1000, now_ms=1),
    ]
    for it in intents:
        assert isinstance(it, PaperIntent) and it.simulation_only is True and it.requires_risk_approval is True
        assert is_actionable(it) is False                                   # bare intent never actionable
        assert is_actionable(approve_with_risk(it, lambda i: (True, []))) is True  # only after risk OK


def test_register_all_15_strategies():
    reg = PaperStrategyRegistry()
    n = L.register_all(reg)
    assert n == 15
    for sid in ("fade_impulse", "mean_reversion", "kelly_sizing", "strategy_ensemble", "rag_evidence_context"):
        assert reg.is_usable(sid, context=RunContext.LIVE)
