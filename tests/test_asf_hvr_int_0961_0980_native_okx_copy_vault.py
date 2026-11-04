"""Fail-closed OKX-to-dispatch boundary coverage."""

from hl_observer.control_plane.dispatch_receipt import DispatchReceipt, native_venue_to_dispatch_boundary_receipt
from hl_observer.venues.okx import capacites, venue_capability_safety_receipt


def _dispatch() -> DispatchReceipt:
    return DispatchReceipt(
        request_id="r1", campaign_id="c1", main_code_sha="a" * 40,
        dataset_repo_sha="b" * 40, creation_phase="COLLECT", phase_epoch=1,
        source_collection_epoch=None, workflow_run_id=None,
        dispatched_at_utc="2026-01-01T00:00:00Z",
    )


def test_asf_hvr_int_0961_positive_boundary() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())["status"] == "PROVEN"


def test_asf_hvr_int_0962_wrong_venue_rejected() -> None:
    row = capacites(); row["venue"] = "other"
    assert native_venue_to_dispatch_boundary_receipt(row, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0963_missing_book_rejected() -> None:
    row = capacites(); row["flux"] = tuple(x for x in row["flux"] if x != "book")
    assert native_venue_to_dispatch_boundary_receipt(row, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0964_orders_forbidden() -> None:
    row = capacites(); row["flux"] = (*row["flux"], "orders")
    assert native_venue_to_dispatch_boundary_receipt(row, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0965_offline_adapter_required() -> None:
    row = capacites(); row["adaptateur"] = "LIVE"
    assert native_venue_to_dispatch_boundary_receipt(row, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0966_network_gate_required() -> None:
    row = capacites(); row["pull_live"] = "ENABLED"
    assert native_venue_to_dispatch_boundary_receipt(row, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0967_dispatch_required() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0968_dispatch_main_sha_checked() -> None:
    row = _dispatch().to_dict(); row["main_code_sha"] = "bad"
    assert native_venue_to_dispatch_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0969_dispatch_phase_checked() -> None:
    row = _dispatch().to_dict(); row["creation_phase"] = "BAD"
    assert native_venue_to_dispatch_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0970_paper_only() -> None:
    out = native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())
    assert out["paper_read_only"] is True and out["real_execution"] is False


def test_asf_hvr_int_0971_network_disabled() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())["network_execution"] is False


def test_asf_hvr_int_0972_dispatch_mutation_disabled() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())["dispatch_mutation"] is False


def test_asf_hvr_int_0973_promotion_disabled() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_int_0974_venue_receipt_safe() -> None:
    assert venue_capability_safety_receipt(capacites())["status"] == "PROVEN"


def test_asf_hvr_int_0975_venue_receipt_rejects_none() -> None:
    assert venue_capability_safety_receipt(None)["status"] == "REJECTED"


def test_asf_hvr_int_0976_bad_flux_rejected() -> None:
    row = capacites(); row["flux"] = None
    assert venue_capability_safety_receipt(row)["status"] == "REJECTED"


def test_asf_hvr_int_0977_bad_boundary_fails_closed() -> None:
    assert native_venue_to_dispatch_boundary_receipt(None, None)["fail_closed"] is True


def test_asf_hvr_int_0978_dispatch_unchanged() -> None:
    dispatch = _dispatch(); before = dispatch.to_dict()
    native_venue_to_dispatch_boundary_receipt(capacites(), dispatch)
    assert dispatch.to_dict() == before


def test_asf_hvr_int_0979_statuses_reported() -> None:
    out = native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())
    assert out["venue_status"] == "PROVEN" and out["dispatch_status"] == "PROVEN"


def test_asf_hvr_int_0980_fail_closed_is_false_only_when_valid() -> None:
    assert native_venue_to_dispatch_boundary_receipt(capacites(), _dispatch())["fail_closed"] is False
