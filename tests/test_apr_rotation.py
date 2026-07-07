"""Distillation HL-Delta: gate APR, rotation d'opportunité, drift delta."""

from __future__ import annotations

from hl_observer.funding.apr_rotation import (
    annualized_yield_pct, decide_rotation, delta_drift_action,
    near_funding_settlement, passes_apr_gate,
)


def test_apr_conversion_and_gate():
    assert abs(annualized_yield_pct(2.5) - 219.0) < 1.0    # 2.5 bps/h ≈ 219%/an
    assert passes_apr_gate(2.5, min_apr_pct=5.0) is True
    assert passes_apr_gate(0.02, min_apr_pct=5.0) is False  # 0.02 bps/h ≈ 1.75%/an < 5%


def test_rotation_enters_best_when_flat():
    d = decide_rotation(current_coin=None, current_rate_bps_per_hour=None,
                        candidates={"HYPE": 3.0, "BTC": 1.0}, min_apr_pct=5.0)
    assert d.action == "ROTATE" and d.to_coin == "HYPE"


def test_rotation_switches_to_better_only_beyond_margin():
    # courant HYPE bon (3 bps/h ~26% APR), BTC légèrement mieux mais sous la marge
    hold = decide_rotation(current_coin="HYPE", current_rate_bps_per_hour=3.0,
                           candidates={"HYPE": 3.0, "BTC": 3.02}, min_apr_pct=5.0, switch_margin_apr_pct=3.0)
    assert hold.action == "HOLD"
    # BTC franchement mieux -> rotation
    rot = decide_rotation(current_coin="HYPE", current_rate_bps_per_hour=3.0,
                          candidates={"HYPE": 3.0, "BTC": 6.0}, min_apr_pct=5.0, switch_margin_apr_pct=3.0)
    assert rot.action == "ROTATE" and rot.to_coin == "BTC"


def test_rotation_exits_when_decayed_no_alternative():
    d = decide_rotation(current_coin="HYPE", current_rate_bps_per_hour=0.05,
                        candidates={"HYPE": 0.05}, min_apr_pct=5.0)
    assert d.action == "EXIT" and d.reason == "CURRENT_BELOW_APR_NO_ALTERNATIVE"


def test_delta_drift_rebalance():
    assert delta_drift_action(100, 100)["action"] == "HOLD"
    r = delta_drift_action(100, 90, rebalance_threshold=0.05)
    assert r["action"] == "REBALANCE" and r["heavier"] == "LONG"


def test_near_funding_settlement_window():
    assert near_funding_settlement(55, window_before=10) is True
    assert near_funding_settlement(30, window_before=10) is False
