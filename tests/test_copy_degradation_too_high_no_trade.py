"""copy_degradation_bps above the cap => COPY_DEGRADATION_TOO_HIGH."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_models import EdgeInputs
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps


def test_high_copy_degradation_flags_no_trade():
    inputs = EdgeInputs(
        leader_expected_edge_bps=50.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        spread_bps=30.0,
        slippage_bps=20.0,
        fee_bps=5.0,
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs)
    assert degradation > 40.0
    assert "COPY_DEGRADATION_TOO_HIGH" in reasons


def test_low_degradation_does_not_flag():
    inputs = EdgeInputs(
        leader_expected_edge_bps=80.0,
        spread_bps=2.0,
        slippage_bps=3.0,
        fee_bps=2.0,
    )
    _, degradation, reasons = compute_edge_remaining_bps(inputs)
    assert degradation <= 40.0
    assert "COPY_DEGRADATION_TOO_HIGH" not in reasons
