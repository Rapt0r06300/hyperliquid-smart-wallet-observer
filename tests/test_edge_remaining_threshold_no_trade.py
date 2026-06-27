"""edge None => EDGE_UNMEASURABLE; edge below threshold => EDGE_REMAINING_TOO_LOW."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_models import EdgeInputs
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps


def test_edge_unmeasurable_when_leader_edge_none():
    edge, _, reasons = compute_edge_remaining_bps(EdgeInputs(leader_expected_edge_bps=None))
    assert edge is None
    assert "EDGE_UNMEASURABLE" in reasons


def test_edge_remaining_too_low_when_below_threshold():
    inputs = EdgeInputs(
        leader_expected_edge_bps=10.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        spread_bps=2.0,
        slippage_bps=1.0,
        fee_bps=2.0,
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs, min_required_bps=8.0)
    assert edge is not None and edge < 8.0
    assert "EDGE_REMAINING_TOO_LOW" in reasons
    assert "COPY_DEGRADATION_TOO_HIGH" not in reasons


def test_edge_above_threshold_has_no_edge_reasons():
    inputs = EdgeInputs(
        leader_expected_edge_bps=100.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        spread_bps=2.0,
        slippage_bps=2.0,
        fee_bps=2.0,
    )
    edge, _, reasons = compute_edge_remaining_bps(inputs, min_required_bps=8.0)
    assert edge is not None and edge >= 8.0
    assert "EDGE_REMAINING_TOO_LOW" not in reasons
    assert "EDGE_UNMEASURABLE" not in reasons
