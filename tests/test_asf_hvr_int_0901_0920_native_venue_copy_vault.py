"""Fail-closed native Hyperliquid-to-phase boundary controls for Copy-Vault."""

from hl_observer.control_plane.phase_state import (
    AlinaPhaseState,
    native_venue_to_phase_boundary_receipt,
)
from hl_observer.venues.hyperliquid import capacites, venue_capability_safety_receipt


def _phase() -> AlinaPhaseState:
    return AlinaPhaseState(
        phase="COLLECT",
        epoch=1,
        collection_started_at_utc="2026-01-01T00:00:00Z",
        analysis_stage=None,
    )


def test_asf_hvr_int_0901_valid_native_boundary_is_proven() -> None:
    receipt = native_venue_to_phase_boundary_receipt(capacites(), _phase())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False


def test_asf_hvr_int_0902_venue_identity_is_required() -> None:
    result = capacites()
    result["venue"] = "other"
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0903_book_flux_is_required() -> None:
    result = capacites()
    result["flux"] = tuple(x for x in result["flux"] if x != "book")
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0904_user_fill_flux_is_required() -> None:
    result = capacites()
    result["flux"] = tuple(x for x in result["flux"] if x != "user_fills")
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0905_orders_flux_is_forbidden() -> None:
    result = capacites()
    result["flux"] = tuple(result["flux"]) + ("orders",)
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0906_offline_adapter_is_required() -> None:
    result = capacites()
    result["adaptateur"] = "LIVE_EXECUTION"
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0907_live_pull_remains_network_gated() -> None:
    result = capacites()
    result["pull_live"] = "ENABLED"
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0908_read_only_surface_is_required() -> None:
    result = capacites()
    result["execution_surface"] = "TRADING"
    assert native_venue_to_phase_boundary_receipt(result, _phase())["status"] == "REJECTED"


def test_asf_hvr_int_0909_phase_is_required() -> None:
    assert native_venue_to_phase_boundary_receipt(capacites(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0910_phase_epoch_is_validated() -> None:
    result = _phase().to_dict()
    result["epoch"] = 0
    assert native_venue_to_phase_boundary_receipt(capacites(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0911_boundary_is_paper_only() -> None:
    receipt = native_venue_to_phase_boundary_receipt(capacites(), _phase())
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0912_boundary_does_not_enable_network_execution() -> None:
    assert native_venue_to_phase_boundary_receipt(capacites(), _phase())["network_execution"] is False


def test_asf_hvr_int_0913_boundary_does_not_mutate_phase() -> None:
    phase = _phase()
    before = phase.to_dict()
    native_venue_to_phase_boundary_receipt(capacites(), phase)
    assert phase.to_dict() == before


def test_asf_hvr_int_0914_venue_receipt_is_fail_closed() -> None:
    assert venue_capability_safety_receipt(None)["status"] == "REJECTED"


def test_asf_hvr_int_0915_venue_receipt_is_read_only() -> None:
    receipt = venue_capability_safety_receipt(capacites())
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0916_phase_status_is_reported() -> None:
    assert native_venue_to_phase_boundary_receipt(capacites(), _phase())["phase_status"] == "PROVEN"


def test_asf_hvr_int_0917_venue_status_is_reported() -> None:
    assert native_venue_to_phase_boundary_receipt(capacites(), _phase())["venue_status"] == "PROVEN"


def test_asf_hvr_int_0918_promotion_is_disabled() -> None:
    assert native_venue_to_phase_boundary_receipt(capacites(), _phase())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_int_0919_boundary_rejects_bad_inputs() -> None:
    receipt = native_venue_to_phase_boundary_receipt(None, None)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


def test_asf_hvr_int_0920_boundary_keeps_execution_disabled() -> None:
    receipt = native_venue_to_phase_boundary_receipt(capacites(), _phase())
    assert receipt["network_execution"] is False
    assert receipt["real_execution"] is False
