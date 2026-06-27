"""V14 #181-185 promotions + V15 #186-200 entry-quality / HL-native / exit modules.
Pure / paper-only / read-only."""

from __future__ import annotations

import pytest

ACCEPT = "EDGE_OK_FOR_LOCAL_SIMULATION"

# ---- #181 event recorder ----
from hl_observer.backtest.entry_event_recorder import EntryEvent, EntryEventRecorder, replay_entry_windows

def test_event_recorder_dedupe_window_replay():
    rec = EntryEventRecorder(max_len=100)
    assert rec.record(EntryEvent(1000, "BTC", "LONG", "WHALE_FILL"))
    assert rec.record(EntryEvent(1000, "BTC", "LONG", "WHALE_FILL")) is False  # dedupe
    rec.record(EntryEvent(1500, "BTC", "LONG", "BOOK"))
    assert len(rec.window(900, 1200, coin="BTC")) == 1
    wins = replay_entry_windows([EntryEvent(5000, "ETH", "LONG", "DECISION"),
                                 EntryEvent(4000, "ETH", "LONG", "BOOK")],
                                trigger_kind="DECISION", pre_ms=2000, post_ms=2000)
    assert wins and wins[0]["trigger_ts_ms"] == 5000 and len(wins[0]["events"]) == 2
    assert len(rec.flush()) == 2 and len(rec) == 0

# ---- #182 exec cost promotion ----
from hl_observer.copy_fidelity.exec_cost_promotion import net_edge_after_exec, apply_exec_cost_promotion, REJECT_REASON as EXEC_REJECT

def test_exec_cost_promotion():
    assert net_edge_after_exec(30, 12) == 18
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=5, min_net_edge_bps=10, authoritative=True) == EXEC_REJECT
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=15, min_net_edge_bps=10, authoritative=True) == ACCEPT
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=5, min_net_edge_bps=10, authoritative=False) == ACCEPT

# ---- #183 entry quality gate ----
from hl_observer.signals.entry_quality_gate import apply_entry_quality_promotion, REJECT_SMART_MONEY, REJECT_DEPTH

def test_entry_quality_promotion():
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=False, depth_ok=True, authoritative=True) == REJECT_SMART_MONEY
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=True, depth_ok=False, authoritative=True) == REJECT_DEPTH
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=None, depth_ok=None, authoritative=True) == ACCEPT
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=False, depth_ok=True, authoritative=False) == ACCEPT

# ---- #184 scoring calibration ----
from hl_observer.scoring.scoring_calibration_promotion import combine_calibrated_score

def test_combine_calibrated_score_monotone():
    base = combine_calibrated_score(base_score=0.6)
    down = combine_calibrated_score(base_score=0.6, deb_weight=0.5)
    assert down < base
    up = combine_calibrated_score(base_score=0.6, maker_band_adj=1.0)
    assert up > base
    assert 0.0 <= combine_calibrated_score(base_score=2.0, emos_factor=5.0) <= 1.0

# ---- #185 feature vector ----
from hl_observer.features.feature_vector_promotion import extended_feature_vector, EXTENDED_FEATURE_KEYS

def test_extended_feature_vector():
    out = extended_feature_vector({"net_edge_bps": 12.0}, eat_flow=0.3, basis_bps=2.0, accumulate=0.5, sigma_blend=1.1)
    assert out["net_edge_bps"] == 12.0
    for k in EXTENDED_FEATURE_KEYS:
        assert k in out

# ---- #186 edge score ----
from hl_observer.signals.edge_score import EdgeScoreInput, compute_edge_score

def test_edge_score_veto_and_points():
    vetoed = compute_edge_score(EdgeScoreInput(stale=True))
    assert vetoed.vetoed and vetoed.score == 0.0 and vetoed.action is False
    strong = compute_edge_score(EdgeScoreInput(bias_ok=True, regime="trend", aligned=True,
                                               mispricing_bps=40, rvol_spike=True, impulse=True))
    assert strong.score >= 60 and strong.action is True
    penalised = compute_edge_score(EdgeScoreInput(bias_ok=True, rsi_overheated=True, depth_degraded=True))
    assert penalised.score < strong.score

# ---- #187 AVWAP ----
from hl_observer.features.avwap import anchored_vwap, avwap_deviation

def test_avwap_and_deviation():
    assert anchored_vwap([10, 20], [1, 1]) == 15.0
    dev = avwap_deviation(price=9.0, prices=[10, 10], volumes=[1, 1], threshold_bps=25)
    assert dev.trigger == "CHEAP" and dev.deviation_bps < 0
    assert avwap_deviation(price=10, prices=[], volumes=[]).trigger == "NO_DATA"

# ---- #188 multi confirmation ----
from hl_observer.signals.multi_confirmation import multi_confirmation, apply_confirmation_promotion, REJECT_REASON as CONF_REJECT

def test_multi_confirmation():
    r = multi_confirmation(rvol_spike=True, obi_confirms=True)
    assert r.count == 2 and r.ok
    assert multi_confirmation().ok is False
    assert apply_confirmation_promotion(score_reason=ACCEPT, confirmed=False, authoritative=True) == CONF_REJECT
    assert apply_confirmation_promotion(score_reason=ACCEPT, confirmed=None, authoritative=True) == ACCEPT

# ---- #189 absorption ----
from hl_observer.features.absorption import absorption_score

def test_absorption_score():
    hi = absorption_score(adverse_move_bps=60, opposing_volume_ratio=0.8, recovery_bps=30)
    lo = absorption_score(adverse_move_bps=5, opposing_volume_ratio=0.1, recovery_bps=0)
    assert hi.panicked and hi.stabilised and hi.score > lo.score
    assert 0.0 <= hi.score <= 1.0

# ---- #190 spike detector ----
from hl_observer.signals.spike_detector import detect_spike

def test_spike_detector():
    assert detect_spike([1, 2]).status == "NO_DATA"
    flat = detect_spike([1, 1, 1, 1, 1, 1])
    assert flat.is_spike is False
    sp = detect_spike([0, 0, 0, 0, 0, 50])
    assert sp.is_spike and sp.direction == "UP"

# ---- #191 OBI delta ----
from hl_observer.features.obi_delta import obi_delta

def test_obi_delta():
    samples = [(1000, -0.1), (5000, 0.0), (9000, 0.3)]
    r = obi_delta(samples, now_ms=11000, windows_ms=(10000, 30000), confirm_threshold=0.1)
    assert r.latest_obi == 0.3
    assert r.confirms_side == "LONG"  # rose from -0.1 to 0.3 over 10s

# ---- #192 RSI overheat ----
from hl_observer.features.rsi_overheat import rsi, rsi_overheat_penalty

def test_rsi_overheat():
    closes = list(range(1, 40))  # strictly rising -> RSI ~100
    val = rsi(closes)
    assert val is not None and val > 70
    pen = rsi_overheat_penalty(val, "LONG")
    assert pen.overheated and pen.penalty_bps == 15.0
    assert rsi_overheat_penalty(val, "SHORT").overheated is False

# ---- #193 regime confidence ----
from hl_observer.signals.regime_confidence import regime_adjusted_confidence

def test_regime_confidence():
    assert regime_adjusted_confidence(1.0, regime="trend", aligned=True) == 1.0
    assert regime_adjusted_confidence(1.0, regime="range", aligned=True) == 0.8
    assert regime_adjusted_confidence(1.0, regime="panic", aligned=True) == 0.0
    assert regime_adjusted_confidence(1.0, regime="trend", aligned=False) == 0.7

# ---- #194 funding ----
from hl_observer.features.funding import funding_filter, funding_carry_usd

def test_funding_filter_and_carry():
    bad = funding_filter(funding_rate=0.001, side="LONG", max_adverse_rate=0.0005)
    assert bad.ok is False and bad.pays_funding
    ok = funding_filter(funding_rate=0.001, side="SHORT", max_adverse_rate=0.0005)
    assert ok.ok and ok.pays_funding is False
    assert funding_carry_usd(funding_rate=0.001, notional_usd=1000, side="LONG", intervals=1) == -1.0
    assert funding_carry_usd(funding_rate=0.001, notional_usd=1000, side="SHORT", intervals=1) == 1.0

# ---- #195 OI delta ----
from hl_observer.signals.oi_delta import oi_delta_signal

def test_oi_delta_signal():
    s = oi_delta_signal(oi_prev=100, oi_now=110, price_prev=100, price_now=101)
    assert s.signal == "NEW_LONGS" and s.side == "LONG"
    s2 = oi_delta_signal(oi_prev=100, oi_now=90, price_prev=100, price_now=101)
    assert s2.signal == "SHORT_UNWIND"

# ---- #196 oracle/mark premium ----
from hl_observer.signals.oracle_mark_premium import oracle_mark_premium

def test_oracle_mark_premium():
    rich = oracle_mark_premium(oracle_px=100, mark_px=100.5, threshold_bps=10)
    assert rich.signal == "MARK_RICH" and rich.side_hint == "SHORT"
    cheap = oracle_mark_premium(oracle_px=100, mark_px=99.5, threshold_bps=10)
    assert cheap.signal == "MARK_CHEAP" and cheap.side_hint == "LONG"

# ---- #197 funding window ----
from hl_observer.signals.funding_window import funding_window_status, apply_funding_window_promotion, REJECT_REASON as FW_REJECT

def test_funding_window():
    near = funding_window_status(seconds_to_funding=30, avoid_window_s=120)
    assert near.in_avoid_window and near.status == "AVOID"
    assert apply_funding_window_promotion(score_reason=ACCEPT, in_avoid_window=True, authoritative=True) == FW_REJECT
    assert apply_funding_window_promotion(score_reason=ACCEPT, in_avoid_window=None, authoritative=True) == ACCEPT

# ---- #198 fee tiers ----
from hl_observer.copy_fidelity.fee_tiers import fee_for_volume, round_trip_cost_bps

def test_fee_tiers():
    low = fee_for_volume(0)
    high = fee_for_volume(600_000_000)
    assert high.taker_bps < low.taker_bps
    rt = round_trip_cost_bps(volume_14d_usd=0, entry_is_maker=False, exit_is_maker=False)
    assert rt == low.taker_bps * 2

# ---- #199 TWAP detector ----
from hl_observer.signals.twap_detector import detect_twap

def test_twap_detector():
    fills = [(1000, 100, "BUY"), (2000, 100, "BUY"), (3000, 100, "BUY"), (4000, 100, "BUY")]
    d = detect_twap(fills)
    assert d.is_twap and d.child_count == 4 and d.side == "BUY"
    irregular = [(1000, 100, "BUY"), (1100, 5, "BUY"), (9000, 300, "SELL")]
    assert detect_twap(irregular).is_twap is False

# ---- #200 ATR trailing stop ----
from hl_observer.risk.atr_trailing_stop import atr, trailing_stop

def test_atr_trailing_stop():
    highs = [10 + i for i in range(20)]
    lows = [9 + i for i in range(20)]
    closes = [9.5 + i for i in range(20)]
    a = atr(highs, lows, closes, period=14)
    assert a is not None and a > 0
    ts = trailing_stop(side="LONG", atr_value=2.0, extreme_price=100, current_price=93, multiplier=3.0)
    assert ts.stop_price == 94.0 and ts.should_exit is True
    ts2 = trailing_stop(side="LONG", atr_value=2.0, extreme_price=100, current_price=96, multiplier=3.0)
    assert ts2.should_exit is False
