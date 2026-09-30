"""GAP: calendrier de marché + coût des refus + bras shadow permanents."""

from __future__ import annotations

from hl_observer.market.calendar_gate import (
    adjusted_min_edge_bps, gate_tightening_factor, is_weekend, session_of,
)
from hl_observer.validation.refusal_cost import refusal_cost_by_reason
from hl_observer.validation.shadow_arms import ShadowArmRegistry


def test_calendar_sessions_and_weekend():
    assert session_of(3) == "ASIA" and session_of(10) == "EUROPE" and session_of(15) == "US" and session_of(22) == "OFF_HOURS"
    assert is_weekend(5) is True and is_weekend(2) is False


def test_gate_tightening_stacks_weekend_and_macro():
    normal = gate_tightening_factor(utc_weekday=2, utc_hour=15, now_ms=1_000_000, macro_events_ms=[])
    assert normal["tightened"] is False and normal["tightening_factor"] == 1.0
    risky = gate_tightening_factor(utc_weekday=6, utc_hour=23, now_ms=1_000_000,
                                   macro_events_ms=[1_000_000], weekend_mult=1.3, off_hours_mult=1.15, macro_mult=1.5)
    assert risky["tightened"] is True
    assert "WEEKEND_THIN_LIQUIDITY" in risky["reasons"] and "MACRO_EVENT_WINDOW" in risky["reasons"]
    assert adjusted_min_edge_bps(28.0, risky) > 28.0   # edge requis resserré


def test_refusal_cost_flags_costly_gate():
    rows = [
        # gate A refuse surtout des gagnants → coûteux
        {"reason": "EDGE_TOO_SMALL", "shadow_net_pnl_usdc": 0.5},
        {"reason": "EDGE_TOO_SMALL", "shadow_net_pnl_usdc": 0.4},
        # gate B refuse surtout des perdants → rentable
        {"reason": "LIQUIDITY_TOO_LOW", "shadow_net_pnl_usdc": -0.6},
        {"reason": "LIQUIDITY_TOO_LOW", "shadow_net_pnl_usdc": -0.3},
    ]
    out = refusal_cost_by_reason(rows)
    by = {r["reason"]: r for r in out["rows"]}
    assert by["EDGE_TOO_SMALL"]["verdict"] == "GATE_TOO_STRICT_COSTS_PNL"
    assert by["LIQUIDITY_TOO_LOW"]["verdict"] == "GATE_PAYS_OFF"
    assert "EDGE_TOO_SMALL" in out["costly_gates"]


def test_refusal_cost_ignores_non_mapping_rows():
    out = refusal_cost_by_reason([
        None,
        "malformed-row",
        {"reason": "SAFE", "shadow_net_pnl_usdc": -0.25},
    ])
    assert out["rows"] == [{
        "reason": "SAFE",
        "refused": 1,
        "would_have_won": 0,
        "missed_pnl_usdc": 0.0,
        "avoided_loss_usdc": 0.25,
        "net_benefit_usdc": 0.25,
        "verdict": "GATE_PAYS_OFF",
    }]
    assert out["costly_gates"] == []


def test_shadow_arms_suggest_promotion_when_candidate_beats_active():
    reg = ShadowArmRegistry("active")
    reg.add_candidate("cand_maker")
    for _ in range(60):
        reg.record({"active": 0.0, "cand_maker": 0.05})   # candidate gagne à chaque tick
    sug = reg.promotion_suggestion(min_ticks=50, min_margin_usdc=1.0)
    assert sug["suggest_promotion"] is True and sug["candidate"] == "cand_maker"


def test_shadow_arms_no_promotion_without_enough_ticks():
    reg = ShadowArmRegistry("active")
    reg.add_candidate("c")
    for _ in range(10):
        reg.record({"active": 0.0, "c": 1.0})
    assert reg.promotion_suggestion(min_ticks=50)["suggest_promotion"] is False
