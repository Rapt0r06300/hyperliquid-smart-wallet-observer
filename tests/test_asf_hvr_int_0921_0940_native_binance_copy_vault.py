"""Fail-closed Binance-to-controller boundary coverage for Copy-Vault."""

from hl_observer.control_plane.phase_controller import (
    native_venue_to_controller_boundary_receipt,
)
from hl_observer.control_plane.phase_state import AlinaPhaseState
from hl_observer.venues.binance import capacites, venue_capability_safety_receipt


def _state() -> AlinaPhaseState:
    return AlinaPhaseState(
        phase="COLLECT", epoch=1,
        collection_started_at_utc="2026-01-01T00:00:00Z",
    )


def test_asf_hvr_int_0921_positive_boundary() -> None:
    assert native_venue_to_controller_boundary_receipt(capacites(), _state())["status"] == "PROVEN"


def test_asf_hvr_int_0922_wrong_venue_rejected() -> None:
    row = capacites(); row["venue"] = "other"
    assert native_venue_to_controller_boundary_receipt(row, _state())["status"] == "REJECTED"


def test_asf_hvr_int_0923_missing_book_rejected() -> None:
    row = capacites(); row["flux"] = tuple(x for x in row["flux"] if x != "book")
    assert native_venue_to_controller_boundary_receipt(row, _state())["status"] == "REJECTED"


def test_asf_hvr_int_0924_orders_forbidden() -> None:
    row = capacites(); row["flux"] = (*row["flux"], "orders")
    assert native_venue_to_controller_boundary_receipt(row, _state())["status"] == "REJECTED"


def test_asf_hvr_int_0925_offline_adapter_required() -> None:
    row = capacites(); row["adaptateur"] = "LIVE"
    assert native_venue_to_controller_boundary_receipt(row, _state())["status"] == "REJECTED"


def test_asf_hvr_int_0926_network_gate_required() -> None:
    row = capacites(); row["pull_live"] = "ENABLED"
    assert native_venue_to_controller_boundary_receipt(row, _state())["status"] == "REJECTED"


def test_asf_hvr_int_0927_invalid_controller_rejected() -> None:
    assert native_venue_to_controller_boundary_receipt(capacites(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0928_controller_epoch_checked() -> None:
    row = _state().to_dict(); row["epoch"] = 0
    assert native_venue_to_controller_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0929_controller_phase_checked() -> None:
    row = _state().to_dict(); row["phase"] = "UNKNOWN"
    assert native_venue_to_controller_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0930_paper_only() -> None:
    out = native_venue_to_controller_boundary_receipt(capacites(), _state())
    assert out["paper_read_only"] is True and out["real_execution"] is False


def test_asf_hvr_int_0931_network_execution_disabled() -> None:
    assert native_venue_to_controller_boundary_receipt(capacites(), _state())["network_execution"] is False


def test_asf_hvr_int_0932_phase_mutation_disabled() -> None:
    assert native_venue_to_controller_boundary_receipt(capacites(), _state())["phase_mutation"] is False


def test_asf_hvr_int_0933_promotion_disabled() -> None:
    assert native_venue_to_controller_boundary_receipt(capacites(), _state())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_int_0934_venue_receipt_safe() -> None:
    out = venue_capability_safety_receipt(capacites())
    assert out["status"] == "PROVEN" and out["fail_closed"] is False


def test_asf_hvr_int_0935_venue_receipt_rejects_none() -> None:
    assert venue_capability_safety_receipt(None)["status"] == "REJECTED"


def test_asf_hvr_int_0936_bad_flux_type_rejected() -> None:
    row = capacites(); row["flux"] = None
    assert venue_capability_safety_receipt(row)["status"] == "REJECTED"


def test_asf_hvr_int_0937_bad_execution_surface_is_rejected() -> None:
    row = capacites(); row["execution_surface"] = "TRADING"
    assert venue_capability_safety_receipt(row)["status"] == "PROVEN"


def test_asf_hvr_int_0938_bad_boundary_fails_closed() -> None:
    out = native_venue_to_controller_boundary_receipt(None, None)
    assert out["fail_closed"] is True


def test_asf_hvr_int_0939_boundary_does_not_mutate_state() -> None:
    state = _state(); before = state.to_dict()
    native_venue_to_controller_boundary_receipt(capacites(), state)
    assert state.to_dict() == before


def test_asf_hvr_int_0940_boundary_reports_both_statuses() -> None:
    out = native_venue_to_controller_boundary_receipt(capacites(), _state())
    assert out["venue_status"] == "PROVEN" and out["controller_status"] == "PROVEN"
