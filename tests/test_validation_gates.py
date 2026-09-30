"""Contrat des gates de validation unifiées (paper-only, verdict de recherche)."""

from __future__ import annotations

from hl_observer.backtesting.validation_gates import (
    out_of_sample_gate,
    profit_factor,
    regime_robustness_gate,
    run_validation_gates,
)


def _gate(report, name):
    return next(g for g in report["gates"] if g["gate"] == name)


def test_robust_strategy_is_deploy_candidate():
    # 40 trades consistants et diversifiés: PF~1.9, edge tient OOS, réparti, drawdown tenable
    trades = [1.5, -0.8] * 20
    r = run_validation_gates(trades, min_trades=30)
    assert r["verdict"] == "DEPLOY_CANDIDATE"
    assert _gate(r, "profit_factor")["passed"] and _gate(r, "out_of_sample")["passed"]
    assert _gate(r, "regime_robustness")["passed"] and _gate(r, "monte_carlo_dd")["passed"]
    assert r["real_execution"] is False


def test_net_negative_rejected_by_profit_factor():
    trades = [1.0, -2.0] * 20            # PF 0.5 -> rejet
    r = run_validation_gates(trades, min_trades=30)
    assert r["verdict"] == "REJECT" and _gate(r, "profit_factor")["passed"] is False


def test_in_sample_only_rejected_by_oos():
    trades = [2.0] * 28 + [-1.0] * 12    # gagnant in-sample, perdant sur les 30% derniers
    r = run_validation_gates(trades, min_trades=30)
    assert _gate(r, "out_of_sample")["passed"] is False and r["verdict"] == "REJECT"


def test_one_lucky_slice_rejected_by_regime():
    # tout le profit dans la 1re tranche, le reste plat/négatif -> pas robuste
    trades = [6.0] * 10 + [-0.05] * 30
    g = regime_robustness_gate(trades, [float(t) for t in trades])
    assert g["passed"] is False and g["top_slice_share"] > 0.7


def test_too_few_trades_rejected_by_sample_size():
    r = run_validation_gates([1.0, -0.5] * 5, min_trades=30)   # 10 trades
    assert _gate(r, "sample_size")["passed"] is False and r["verdict"] == "REJECT"


def test_profit_factor_helpers():
    assert profit_factor([2, -1, 2, -1]) == 2.0
    assert profit_factor([1, 2, 3]) == float("inf")            # aucune perte
    assert profit_factor([-1, -2]) == 0.0                       # aucun gain


def test_oos_gate_reports_both_windows():
    g = out_of_sample_gate([1.0] * 10)
    assert "pf_in_sample" in g and "pf_out_sample" in g and g["n_test"] == 3


def test_lookahead_skipped_without_events():
    r = run_validation_gates([1.5, -0.8] * 20)
    lk = _gate(r, "lookahead")
    assert lk.get("skipped") is True and lk["passed"] is True    # honnête: pas d'events -> skip


def test_lookahead_rejects_future_data_event():
    events = [{"decision_ts_ms": 1_000, "data_ts_ms": 1_001}]
    r = run_validation_gates([1.5, -0.8] * 20, events=events)
    lk = _gate(r, "lookahead")
    assert lk["passed"] is False
    assert lk["violation_count"] == 1
    assert r["verdict"] == "REJECT"
    assert r["real_execution"] is False
