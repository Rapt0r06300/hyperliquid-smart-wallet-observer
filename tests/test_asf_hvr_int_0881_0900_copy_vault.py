"""Fail-closed dispatch-to-PnL boundary controls for Copy-Vault."""

from datetime import datetime

from hl_observer.control_plane.dispatch_receipt import DispatchReceipt
from hl_observer.control_plane.module_pnl_proof import dispatch_to_pnl_boundary_receipt


def _dispatch() -> DispatchReceipt:
    return DispatchReceipt(
        request_id="r1",
        campaign_id="c1",
        main_code_sha="a" * 40,
        dataset_repo_sha="b" * 40,
        creation_phase="COLLECT",
        phase_epoch=1,
        source_collection_epoch=None,
        workflow_run_id=None,
        dispatched_at_utc="2026-01-01T00:00:00Z",
    )


def _pnl() -> dict[str, object]:
    return {"paper_only": True, "read_only": True, "real_execution": False, "aggregate_allowed": False}


def test_asf_hvr_int_0881_valid_boundary_is_proven() -> None:
    receipt = dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False


def test_asf_hvr_int_0882_dispatch_is_required() -> None:
    assert dispatch_to_pnl_boundary_receipt({}, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0883_dispatch_real_execution_is_rejected() -> None:
    raw = _dispatch().to_dict()
    raw["status"] = "COMPLETE"
    raw["terminal_at_utc"] = "2026-01-01T00:00:00Z"
    raw["terminal_evidence_digest"] = "a" * 64
    assert dispatch_to_pnl_boundary_receipt(raw, _pnl())["status"] == "PROVEN"


def test_asf_hvr_int_0884_pnl_requires_paper_only() -> None:
    result = _pnl()
    result["paper_only"] = False
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0885_pnl_requires_read_only() -> None:
    result = _pnl()
    result["read_only"] = False
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0886_pnl_real_execution_is_rejected() -> None:
    result = _pnl()
    result["real_execution"] = True
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0887_pnl_aggregation_is_disabled() -> None:
    result = _pnl()
    result["aggregate_allowed"] = True
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), result)["status"] == "REJECTED"


def test_asf_hvr_int_0888_pnl_mapping_is_required() -> None:
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), None)["status"] == "REJECTED"


def test_asf_hvr_int_0889_dispatch_identity_is_checked() -> None:
    raw = _dispatch().to_dict()
    raw["request_id"] = ""
    assert dispatch_to_pnl_boundary_receipt(raw, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0890_dispatch_phase_is_checked() -> None:
    raw = _dispatch().to_dict()
    raw["creation_phase"] = "UNKNOWN"
    assert dispatch_to_pnl_boundary_receipt(raw, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0891_boundary_is_non_promoting() -> None:
    receipt = dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())
    assert receipt["economic_promotion"] is False
    assert receipt["aggregate_allowed"] is False


def test_asf_hvr_int_0892_boundary_is_paper_only() -> None:
    receipt = dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())
    assert receipt["paper_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0893_boundary_does_not_mutate_dispatch() -> None:
    dispatch = _dispatch()
    before = dispatch.to_dict()
    dispatch_to_pnl_boundary_receipt(dispatch, _pnl())
    assert dispatch.to_dict() == before


def test_asf_hvr_int_0894_boundary_does_not_mutate_pnl() -> None:
    pnl = _pnl()
    before = dict(pnl)
    dispatch_to_pnl_boundary_receipt(_dispatch(), pnl)
    assert pnl == before


def test_asf_hvr_int_0895_boundary_reports_dispatch_status() -> None:
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())["dispatch_status"] == "PROVEN"


def test_asf_hvr_int_0896_boundary_reports_pnl_status() -> None:
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())["pnl_status"] == "PROVEN"


def test_asf_hvr_int_0897_boundary_rejects_missing_pnl_flag() -> None:
    assert dispatch_to_pnl_boundary_receipt(_dispatch(), {"paper_only": True})["status"] == "REJECTED"


def test_asf_hvr_int_0898_boundary_rejects_bad_dispatch_timestamp() -> None:
    raw = _dispatch().to_dict()
    raw["dispatched_at_utc"] = "bad"
    assert dispatch_to_pnl_boundary_receipt(raw, _pnl())["status"] == "REJECTED"


def test_asf_hvr_int_0899_boundary_is_fail_closed_on_bad_input() -> None:
    receipt = dispatch_to_pnl_boundary_receipt(None, None)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


def test_asf_hvr_int_0900_boundary_preserves_safe_contract() -> None:
    receipt = dispatch_to_pnl_boundary_receipt(_dispatch(), _pnl())
    assert receipt["mutation"] is False
    assert receipt["phase_mutation"] is False
