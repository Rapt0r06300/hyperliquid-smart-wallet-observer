"""P2: réconciliation funding réel vs prédit + drift exit + alerte dérive."""

from __future__ import annotations

from hl_observer.funding.funding_reconciliation import (
    cumulative_drift_alert, funding_drift_exit, reconcile_funding,
)


def test_reconcile_pairs_predicted_and_actual():
    pred = [{"pair_id": "HYPE:1", "amount_usdc": 0.025}, {"pair_id": "BTC:1", "amount_usdc": 0.010}]
    actual = [{"pair_id": "HYPE:1", "amount_usdc": 0.022}, {"pair_id": "BTC:1", "amount_usdc": 0.011}]
    r = reconcile_funding(pred, actual)
    assert r["status"] == "OK" and r["pairs"] == 2
    assert abs(r["total_predicted_usdc"] - 0.035) < 1e-9
    assert abs(r["total_actual_usdc"] - 0.033) < 1e-9
    assert r["total_abs_error_usdc"] == 0.004   # |0.022-0.025| + |0.011-0.010|


def test_reconcile_insufficient_when_no_actual():
    assert reconcile_funding([{"pair_id": "X", "amount_usdc": 1}], [])["status"] == "INSUFFICIENT_ACTUAL_PAYMENTS"


def test_drift_exit_on_reversal_and_collapse():
    assert funding_drift_exit(5.0, -0.2)["reason"] == "FUNDING_REVERSED"   # signe inversé
    assert funding_drift_exit(5.0, 0.3, exit_edge_bps_per_hour=0.65)["reason"] == "FUNDING_EDGE_COLLAPSED"
    assert funding_drift_exit(5.0, 4.0)["exit"] is False                    # tient encore


def test_drift_alert_triggers_beyond_tolerance():
    recon = reconcile_funding(
        [{"pair_id": "A", "amount_usdc": 1.0}],
        [{"pair_id": "A", "amount_usdc": 0.2}],
    )
    alert = cumulative_drift_alert(recon, max_abs_error_usdc=0.5)
    assert alert["alert"] is True and alert["reason"] == "FUNDING_MODEL_DRIFT"
    ok = cumulative_drift_alert(
        reconcile_funding([{"pair_id": "A", "amount_usdc": 1.0}], [{"pair_id": "A", "amount_usdc": 0.98}]),
        max_abs_error_usdc=0.5,
    )
    assert ok["alert"] is False
