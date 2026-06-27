from __future__ import annotations

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.opportunity_calibration import apply_opportunity_calibration, calibration_summary


def test_calibration_sets_wider_scan_values() -> None:
    cfg = apply_opportunity_calibration(DydxV4Config())
    s = calibration_summary(cfg)

    assert s["max_signal_age_ms"] >= 90000
    assert s["fast_scanner_hot_capacity"] >= 2500
    assert s["max_decision_wallets"] >= 3000
    assert s["rest_poll_cap"] >= 250
