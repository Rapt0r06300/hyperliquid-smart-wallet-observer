from hl_observer.risk.stress_test import stress_pnl, stress_scenarios, worst_case
from hl_observer.risk.risk_panel import build_risk_panel


def test_stress_long_short_directions():
    pos = [{"side": "LONG", "notional_usdt": 100}, {"side": "SHORT", "notional_usdt": 50}]
    # +10%: long +10, short -5 => +5 ; -10%: long -10, short +5 => -5
    assert stress_pnl(pos, shock_pct=0.10) == 5.0
    assert stress_pnl(pos, shock_pct=-0.10) == -5.0
    wc = worst_case(pos)
    assert wc["pnl_usdc"] <= 0.0


def test_risk_panel_with_data():
    pnls = [2.0, -1.0, 3.0, -4.0, 1.0, -0.5, 2.5, -3.0, 0.5, -1.5]
    pos = [{"side": "LONG", "notional_usdt": 200}]
    rep = build_risk_panel(recent_trade_pnls=pnls, open_positions=pos, equity=995.0)
    assert rep["empty"] is False and rep["context_only"] is True
    assert rep["var_usdc"] is not None and rep["cvar_usdc"] is not None
    assert rep["worst_case"]["pnl_usdc"] < 0  # a long loses if price drops
    assert rep["open_exposure_usdc"] == 200.0
    assert "Risque" in rep["plain_summary"]


def test_risk_panel_halts_on_big_total_loss():
    rep = build_risk_panel(recent_trade_pnls=[-1, -2], open_positions=[], equity=550.0, start_equity=1000.0)
    assert rep["total_loss_pct"] >= 40.0 and rep["halted"] is True
    assert "DÉCLENCHÉ" in rep["plain_summary"]


def test_risk_panel_empty_is_honest():
    rep = build_risk_panel()
    assert rep["empty"] is True and rep["var_usdc"] is None and "Pas encore" in rep["plain_summary"]
