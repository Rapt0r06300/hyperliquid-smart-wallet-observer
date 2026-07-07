"""V15 #201-209 — scale-out, pyramiding, correlated exposure, slippage, session filter,
data-quality gap, scan breadth, /metrics, leader hotness. Pure / paper-only / read-only."""

from __future__ import annotations

import pytest

ACCEPT = "EDGE_OK_FOR_LOCAL_SIMULATION"

# #201
from hl_observer.risk.scale_out import scale_out_plan, move_to_breakeven

def test_scale_out_and_breakeven():
    plan = scale_out_plan(entry_price=100, current_price=101, side="LONG", tranches=[(50, 0.5), (150, 0.5)])
    assert plan[0].take is True and plan[1].take is False   # +100bps hits first tranche only
    moved, stop = move_to_breakeven(entry_price=100, current_price=100.4, side="LONG", trigger_bps=30)
    assert moved and stop == 100.0
    assert move_to_breakeven(entry_price=100, current_price=100.1, side="LONG", trigger_bps=30)[0] is False

# #202
from hl_observer.signals.pyramiding import pyramiding_decision

def test_pyramiding():
    ok = pyramiding_decision(in_profit_bps=40, confirmation=True, current_adds=0)
    assert ok.add
    assert pyramiding_decision(in_profit_bps=40, confirmation=True, current_adds=2, max_adds=2).add is False
    assert pyramiding_decision(in_profit_bps=5, confirmation=True, current_adds=0).add is False
    assert pyramiding_decision(in_profit_bps=40, confirmation=False, current_adds=0).add is False

# #203
from hl_observer.risk.correlated_exposure import Position, correlated_exposure_check

def test_correlated_exposure_caps():
    book = [Position("ETH", "LONG", 200, 1.2)]
    groups = {"ETH": "L1", "SOL": "L1"}
    v = correlated_exposure_check(book, Position("SOL", "LONG", 200, 1.1),
                                  correlation_groups=groups, max_cluster_notional_usd=300)
    assert v.ok is False and v.reason == "CORRELATED_CLUSTER_CAP"
    v2 = correlated_exposure_check([], Position("BTC", "LONG", 100, 1.0),
                                   max_cluster_notional_usd=300, max_net_beta_usd=600)
    assert v2.ok is True

# #204
from hl_observer.copy_fidelity.slippage_model import slippage_bps

def test_slippage_model():
    liquid = slippage_bps(notional_usd=1000, liquidity_score=0.95)
    illiquid = slippage_bps(notional_usd=1000, liquidity_score=0.2)
    assert illiquid > liquid >= 1.0
    big = slippage_bps(notional_usd=5000, liquidity_score=0.2)
    assert big > illiquid

# #205
from hl_observer.signals.session_filter import session_status, apply_session_promotion, REJECT_REASON as SESS_REJECT

def test_session_filter():
    assert session_status(4, dead_hours_utc=(3, 4, 5)).active is False
    assert session_status(14, dead_hours_utc=(3, 4, 5)).active is True
    assert apply_session_promotion(score_reason=ACCEPT, session_active=False, authoritative=True) == SESS_REJECT
    assert apply_session_promotion(score_reason=ACCEPT, session_active=None, authoritative=True) == ACCEPT

# #206
from hl_observer.realtime.data_quality_gap import data_quality_status, detect_timestamp_gaps, apply_data_quality_promotion, REJECT_REASON as DQ_REJECT

def test_data_quality_gap():
    n, biggest = detect_timestamp_gaps([0, 1000, 2000, 20000], max_gap_ms=5000)
    assert n == 1 and biggest == 18000
    st = data_quality_status(sequence_numbers=[1, 2, 4], timestamps_ms=[0, 100])
    assert st.ok is False and st.reason == "SEQUENCE_GAP"
    clean = data_quality_status(sequence_numbers=[1, 2, 3], timestamps_ms=[0, 100, 200])
    assert clean.ok is True
    assert apply_data_quality_promotion(score_reason=ACCEPT, data_ok=False, authoritative=True) == DQ_REJECT
    assert apply_data_quality_promotion(score_reason=ACCEPT, data_ok=None, authoritative=True) == ACCEPT

# #207
from hl_observer.markets.scan_breadth import bounded_scan_breadth

def test_scan_breadth_bounded():
    r = bounded_scan_breadth(["a", "b", "c", "d", "e"], max_coins=3, must_include=["z"])
    assert r.coins[0] == "Z" and len(r.coins) == 3 and r.capped is True
    assert "D" in r.dropped or "E" in r.dropped

# #208
from hl_observer.realtime.metrics_endpoint import build_metrics, format_metrics_prometheus

def test_metrics_endpoint():
    m = build_metrics(messages=100, fills=20, elapsed_s=10, errors=1, reconnects=2, open_positions=5)
    assert m.throughput_msg_per_s == 10.0 and m.fills_per_s == 2.0
    text = format_metrics_prometheus(m)
    assert "hypersmart_execution_forbidden 1" in text and "hypersmart_paper_local_only 1" in text

# #209
from hl_observer.wallets.leader_hotness import leader_hotness

def test_leader_hotness():
    now = 10_000_000
    hot = leader_hotness([(now - 1000, 50), (now - 2000, 80), (now - 3000, 40)], now_ms=now, halflife_ms=86_400_000)
    cold = leader_hotness([(now - 1000, -50), (now - 2000, -80)], now_ms=now, halflife_ms=86_400_000)
    assert hot.hotness > cold.hotness
    assert hot.trend in {"HOT", "WARM"}
    assert leader_hotness([], now_ms=now).trend == "COLD"
