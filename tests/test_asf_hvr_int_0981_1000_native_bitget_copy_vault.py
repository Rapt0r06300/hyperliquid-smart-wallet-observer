"""Fail-closed Bitget-to-independent-PnL boundary coverage."""

from hl_observer.control_plane.module_pnl_proof import (
    native_venue_to_pnl_boundary_receipt,
)
from hl_observer.venues.bitget import capacites, venue_capability_safety_receipt


def _pnl() -> dict[str, object]:
    return {"paper_only": True, "read_only": True, "real_execution": False, "aggregate_allowed": False}


def test_asf_hvr_int_0981_positive_boundary() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), _pnl())["status"] == "PROVEN"


def test_asf_hvr_int_0982_wrong_venue_rejected() -> None:
    row = capacites(); row["venue"] = "other"
    assert native_venue_to_pnl_boundary_receipt(row, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0983_missing_book_rejected() -> None:
    row = capacites(); row["flux"] = tuple(x for x in row["flux"] if x != "book")
    assert native_venue_to_pnl_boundary_receipt(row, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0984_orders_forbidden() -> None:
    row = capacites(); row["flux"] = (*row["flux"], "orders")
    assert native_venue_to_pnl_boundary_receipt(row, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0985_offline_adapter_required() -> None:
    row = capacites(); row["adaptateur"] = "LIVE"
    assert native_venue_to_pnl_boundary_receipt(row, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0986_network_gate_required() -> None:
    row = capacites(); row["pull_live"] = "ENABLED"
    assert native_venue_to_pnl_boundary_receipt(row, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0987_pnl_required() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0988_pnl_must_be_read_only() -> None:
    row = _pnl(); row["read_only"] = False
    assert native_venue_to_pnl_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0989_pnl_cannot_execute() -> None:
    row = _pnl(); row["real_execution"] = True
    assert native_venue_to_pnl_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0990_pnl_aggregate_forbidden() -> None:
    row = _pnl(); row["aggregate_allowed"] = True
    assert native_venue_to_pnl_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0991_paper_only() -> None:
    out = native_venue_to_pnl_boundary_receipt(capacites(), _pnl())
    assert out["paper_only"] is True and out["real_execution"] is False


def test_asf_hvr_int_0992_network_disabled() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), _pnl())["network_execution"] is False


def test_asf_hvr_int_0993_aggregate_disabled() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), _pnl())["aggregate_allowed"] is False


def test_asf_hvr_int_0994_pnl_mutation_disabled() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), _pnl())["pnl_mutation"] is False


def test_asf_hvr_int_0995_venue_receipt_safe() -> None:
    assert venue_capability_safety_receipt(capacites())["status"] == "PROVEN"


def test_asf_hvr_int_0996_venue_receipt_rejects_none() -> None:
    assert venue_capability_safety_receipt(None)["status"] == "REJECTED"


def test_asf_hvr_int_0997_bad_flux_rejected() -> None:
    row = capacites(); row["flux"] = None
    assert venue_capability_safety_receipt(row)["status"] == "REJECTED"


def test_asf_hvr_int_0998_bad_boundary_fails_closed() -> None:
    assert native_venue_to_pnl_boundary_receipt(None, None)["fail_closed"] is True


def test_asf_hvr_int_0999_statuses_reported() -> None:
    out = native_venue_to_pnl_boundary_receipt(capacites(), _pnl())
    assert out["venue_status"] == "PROVEN" and out["pnl_status"] == "PROVEN"


def test_asf_hvr_int_1000_fail_closed_is_false_only_when_valid() -> None:
    assert native_venue_to_pnl_boundary_receipt(capacites(), _pnl())["fail_closed"] is False
