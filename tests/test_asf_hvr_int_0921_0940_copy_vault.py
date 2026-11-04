"""Fail-closed controller-to-dispatch boundary controls for Copy-Vault."""

from hl_observer.control_plane.dispatch_receipt import DispatchReceipt
from hl_observer.control_plane.phase_controller import controller_to_dispatch_boundary_receipt
from hl_observer.control_plane.phase_state import AlinaPhaseState


def _controller() -> AlinaPhaseState:
    return AlinaPhaseState(
        phase="COLLECT",
        epoch=1,
        collection_started_at_utc="2026-01-01T00:00:00Z",
        analysis_stage=None,
    )


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


def test_asf_hvr_int_0921_valid_boundary_is_proven() -> None:
    receipt = controller_to_dispatch_boundary_receipt(_controller(), _dispatch())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False


def test_asf_hvr_int_0922_controller_is_required() -> None:
    assert controller_to_dispatch_boundary_receipt({}, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0923_dispatch_is_required() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0924_phase_mismatch_is_rejected() -> None:
    raw = _dispatch().to_dict()
    raw["creation_phase"] = "ANALYZE"
    raw["source_collection_epoch"] = 1
    assert controller_to_dispatch_boundary_receipt(_controller(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0925_epoch_mismatch_is_rejected() -> None:
    raw = _dispatch().to_dict()
    raw["phase_epoch"] = 2
    assert controller_to_dispatch_boundary_receipt(_controller(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0926_controller_phase_is_validated() -> None:
    raw = _controller().to_dict()
    raw["phase"] = "UNKNOWN"
    assert controller_to_dispatch_boundary_receipt(raw, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0927_controller_epoch_is_validated() -> None:
    raw = _controller().to_dict()
    raw["epoch"] = 0
    assert controller_to_dispatch_boundary_receipt(raw, _dispatch())["status"] == "REJECTED"


def test_asf_hvr_int_0928_dispatch_identity_is_validated() -> None:
    raw = _dispatch().to_dict()
    raw["request_id"] = ""
    assert controller_to_dispatch_boundary_receipt(_controller(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0929_dispatch_sha_is_validated() -> None:
    raw = _dispatch().to_dict()
    raw["main_code_sha"] = "bad"
    assert controller_to_dispatch_boundary_receipt(_controller(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0930_boundary_is_paper_only() -> None:
    receipt = controller_to_dispatch_boundary_receipt(_controller(), _dispatch())
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0931_boundary_does_not_mutate_controller() -> None:
    controller = _controller()
    before = controller.to_dict()
    controller_to_dispatch_boundary_receipt(controller, _dispatch())
    assert controller.to_dict() == before


def test_asf_hvr_int_0932_boundary_does_not_mutate_dispatch() -> None:
    dispatch = _dispatch()
    before = dispatch.to_dict()
    controller_to_dispatch_boundary_receipt(_controller(), dispatch)
    assert dispatch.to_dict() == before


def test_asf_hvr_int_0933_phase_match_is_reported() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), _dispatch())["phase_match"] is True


def test_asf_hvr_int_0934_epoch_match_is_reported() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), _dispatch())["epoch_match"] is True


def test_asf_hvr_int_0935_dispatch_mutation_is_disabled() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), _dispatch())["dispatch_mutation"] is False


def test_asf_hvr_int_0936_controller_mutation_is_disabled() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), _dispatch())["phase_mutation"] is False


def test_asf_hvr_int_0937_promotion_is_disabled() -> None:
    assert controller_to_dispatch_boundary_receipt(_controller(), _dispatch())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_int_0938_boundary_reports_source_statuses() -> None:
    receipt = controller_to_dispatch_boundary_receipt(_controller(), _dispatch())
    assert receipt["controller_status"] == "PROVEN"
    assert receipt["dispatch_status"] == "PROVEN"


def test_asf_hvr_int_0939_boundary_is_fail_closed_on_bad_input() -> None:
    receipt = controller_to_dispatch_boundary_receipt(None, None)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


def test_asf_hvr_int_0940_boundary_rejects_non_matching_phase_and_epoch() -> None:
    raw = _dispatch().to_dict()
    raw["creation_phase"] = "ANALYZE"
    raw["phase_epoch"] = 3
    raw["source_collection_epoch"] = 1
    receipt = controller_to_dispatch_boundary_receipt(_controller(), raw)
    assert receipt["phase_match"] is False
    assert receipt["epoch_match"] is False
