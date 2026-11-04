"""Fail-closed PnL-to-economic-proof boundary controls for Copy-Vault."""

from hl_observer.control_plane.module_pnl_proof import pnl_state_safety_receipt
from hl_observer.simulation.economic_proof_controls import (
    INDEPENDENT_AUDIT_SCHEMA,
    pnl_to_economic_proof_boundary_receipt,
)


def _pnl() -> dict[str, object]:
    return {"paper_only": True, "read_only": True, "real_execution": False, "aggregate_allowed": False}


def _economic() -> dict[str, object]:
    return {
        "schema_version": INDEPENDENT_AUDIT_SCHEMA,
        "family": "copy_vault",
        "data_sha256": "a" * 64,
        "code_sha256": "b" * 64,
        "freeze_sha256": "c" * 64,
        "cutoff_ts_ms": 1,
        "paper_only": True,
        "real_execution": False,
        "economic_proof_status": "UNMEASURABLE",
    }


def test_asf_hvr_int_0901_valid_boundary_is_proven() -> None:
    receipt = pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False


def test_asf_hvr_int_0902_pnl_requires_paper_only() -> None:
    result = _pnl()
    result["paper_only"] = False
    assert pnl_to_economic_proof_boundary_receipt(result, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0903_pnl_requires_read_only() -> None:
    result = _pnl()
    result["read_only"] = False
    assert pnl_to_economic_proof_boundary_receipt(result, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0904_pnl_real_execution_is_rejected() -> None:
    result = _pnl()
    result["real_execution"] = True
    assert pnl_to_economic_proof_boundary_receipt(result, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0905_pnl_aggregation_is_rejected() -> None:
    result = _pnl()
    result["aggregate_allowed"] = True
    assert pnl_to_economic_proof_boundary_receipt(result, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0906_pnl_mapping_is_required() -> None:
    assert pnl_to_economic_proof_boundary_receipt(None, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0907_economic_schema_is_required() -> None:
    result = _economic()
    result["schema_version"] = "unknown"
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0908_economic_hashes_are_required() -> None:
    result = _economic()
    result["data_sha256"] = ""
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0909_economic_cutoff_is_required() -> None:
    result = _economic()
    result["cutoff_ts_ms"] = 0
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0910_economic_status_is_explicit() -> None:
    result = _economic()
    result["economic_proof_status"] = "UNKNOWN"
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0911_boundary_is_non_promoting() -> None:
    receipt = pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())
    assert receipt["economic_promotion"] is False
    assert receipt["paper_read_only"] is True


def test_asf_hvr_int_0912_boundary_is_not_an_economic_certificate() -> None:
    receipt = pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())
    assert receipt["verdict"] == "PNL_TO_ECONOMIC_PROOF_BOUNDARY_SAFE"


def test_asf_hvr_int_0913_boundary_does_not_mutate_pnl() -> None:
    result = _pnl()
    before = dict(result)
    pnl_to_economic_proof_boundary_receipt(result, _economic())
    assert result == before


def test_asf_hvr_int_0914_boundary_does_not_mutate_economic_result() -> None:
    result = _economic()
    before = dict(result)
    pnl_to_economic_proof_boundary_receipt(_pnl(), result)
    assert result == before


def test_asf_hvr_int_0915_boundary_reports_pnl_status() -> None:
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())["pnl_status"] == "PROVEN"


def test_asf_hvr_int_0916_boundary_reports_economic_status() -> None:
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())["economic_status"] == "PROVEN"


def test_asf_hvr_int_0917_boundary_rejects_missing_pnl_flag() -> None:
    assert pnl_to_economic_proof_boundary_receipt({"paper_only": True}, _economic())["status"] == "REJECTED"


def test_asf_hvr_int_0918_boundary_rejects_missing_economic_flag() -> None:
    result = _economic()
    result.pop("paper_only")
    assert pnl_to_economic_proof_boundary_receipt(_pnl(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0919_boundary_is_fail_closed_on_bad_input() -> None:
    receipt = pnl_to_economic_proof_boundary_receipt(None, None)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


def test_asf_hvr_int_0920_boundary_keeps_aggregate_disabled() -> None:
    receipt = pnl_to_economic_proof_boundary_receipt(_pnl(), _economic())
    assert receipt["aggregate_allowed"] is False
    assert receipt["pnl_mutation"] is False
