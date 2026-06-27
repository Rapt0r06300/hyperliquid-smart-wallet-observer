"""Locks the LIVE wiring composition used in routes.opportunity_metrics + dashboard:
#182 exec-cost net-edge, #183 entry-quality, #166 freshness panel, #208 /metrics.
Pure / paper-only / read-only — mirrors the exact formula sequence in routes."""

from __future__ import annotations

ACCEPT = "EDGE_OK_FOR_LOCAL_SIMULATION"

from hl_observer.copy_fidelity.slippage_model import slippage_bps
from hl_observer.copy_fidelity.exec_cost_model import model_exec_costs, net_edge_after_costs
from hl_observer.copy_fidelity.exec_cost_promotion import apply_exec_cost_promotion, REJECT_REASON as EXEC_REJECT
from hl_observer.signals.entry_quality_gate import apply_entry_quality_promotion, REJECT_SMART_MONEY, REJECT_DEPTH


def _net_after_exec(gross_edge_bps, notional, liquidity):
    slip = slippage_bps(notional_usd=notional, liquidity_score=liquidity)
    costs = model_exec_costs(fee_bps=4.5, half_spread_bps=1.5, slippage_bps=slip, latency_bps=0.0, is_maker=False)
    return net_edge_after_costs(gross_edge_bps=gross_edge_bps, costs=costs)


def test_exec_cost_live_formula_thin_liquidity_kills_marginal_edge():
    # marginal gross edge, big size on thin liquidity -> net after exec < 0 -> reject when authoritative
    net = _net_after_exec(gross_edge_bps=8.0, notional=5000.0, liquidity=0.2)
    assert net < 0
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=net, min_net_edge_bps=0.0, authoritative=True) == EXEC_REJECT
    # strong edge on deep liquidity survives
    net2 = _net_after_exec(gross_edge_bps=40.0, notional=40.0, liquidity=0.95)
    assert net2 > 0
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=net2, min_net_edge_bps=0.0, authoritative=True) == ACCEPT
    # shadow (flag off) never blocks
    assert apply_exec_cost_promotion(score_reason=ACCEPT, net_edge_bps=net, min_net_edge_bps=0.0, authoritative=False) == ACCEPT


def test_entry_quality_live_from_real_signals():
    # depth_ok from real liquidity vs config min; smart-money from leader_score (confidence*100)
    min_liq = 0.22
    def depth_ok(liq):
        return (liq >= min_liq) if min_liq > 0 else None
    def sm_ok(conf):
        return (conf * 100.0) >= 60.0
    # weak leader -> reject (authoritative)
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=sm_ok(0.4), depth_ok=depth_ok(0.9), authoritative=True) == REJECT_SMART_MONEY
    # thin liquidity -> reject
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=sm_ok(0.8), depth_ok=depth_ok(0.1), authoritative=True) == REJECT_DEPTH
    # strong leader + ok liquidity -> pass
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=sm_ok(0.8), depth_ok=depth_ok(0.5), authoritative=True) == ACCEPT
    # shadow never blocks
    assert apply_entry_quality_promotion(score_reason=ACCEPT, smart_money_ok=sm_ok(0.1), depth_ok=depth_ok(0.0), authoritative=False) == ACCEPT


def test_freshness_panel_builder_graceful_on_empty(tmp_path):
    from hl_observer.realtime.freshness_audit import build_freshness_audit_from_logs
    fa = build_freshness_audit_from_logs(tmp_path)   # no logs -> honest empty
    assert fa.status == "NO_SIGNAL_AGE_DATA" and fa.samples == 0


def test_metrics_text_is_readonly():
    from hl_observer.realtime.metrics_endpoint import build_metrics, format_metrics_prometheus
    txt = format_metrics_prometheus(build_metrics(open_positions=3))
    assert "hypersmart_open_positions 3" in txt
    assert "hypersmart_execution_forbidden 1" in txt
