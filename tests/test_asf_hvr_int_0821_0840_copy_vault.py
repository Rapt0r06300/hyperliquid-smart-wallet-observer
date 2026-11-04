from hl_observer.control_plane.phase_controller import (
    economic_freeze_to_controller_boundary_receipt,
)
from hl_observer.control_plane.phase_state import AlinaPhaseState


def _freeze(**overrides):
    result = {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "family": "copy_vault",
        "freeze_hash": "a" * 64,
        "data_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "frozen_at_ms": 100,
        "parameters_sha256": "p" * 64,
        "paper_only": True,
        "real_execution": False,
    }
    result.update(overrides)
    return result


def _controller():
    return AlinaPhaseState(
        phase="ANALYZE",
        epoch=4,
        collection_started_at_utc="2026-01-01T00:00:00Z",
        collection_cutoff_at_utc="2026-01-01T01:00:00Z",
        source_collection_epoch=4,
        analysis_stage="OOS",
    )


def test_asf_hvr_0821_normal_fixture_joins_safely():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), _controller())["status"] == "PROVEN"


def test_asf_hvr_0822_missing_freeze_field_fails_closed():
    freeze = _freeze()
    freeze.pop("data_sha256")
    assert economic_freeze_to_controller_boundary_receipt(freeze, _controller())["status"] == "REJECTED"


def test_asf_hvr_0823_invalid_controller_state_fails_closed():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), {"phase": "ANALYZE"})["status"] == "REJECTED"


def test_asf_hvr_0824_freeze_timestamp_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(frozen_at_ms=0), _controller())["status"] == "REJECTED"


def test_asf_hvr_0825_freeze_schema_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(schema_version="wrong"), _controller())["status"] == "REJECTED"


def test_asf_hvr_0826_freeze_hash_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(freeze_hash=None), _controller())["status"] == "REJECTED"


def test_asf_hvr_0827_data_hash_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(data_sha256=""), _controller())["status"] == "REJECTED"


def test_asf_hvr_0828_config_hash_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(config_sha256=""), _controller())["status"] == "REJECTED"


def test_asf_hvr_0829_parameters_hash_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(parameters_sha256=""), _controller())["status"] == "REJECTED"


def test_asf_hvr_0830_paper_only_is_required():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(paper_only=False), _controller())["status"] == "REJECTED"


def test_asf_hvr_0831_real_execution_is_rejected():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(real_execution=True), _controller())["status"] == "REJECTED"


def test_asf_hvr_0832_controller_epoch_is_validated():
    controller = _controller()
    controller.epoch = 0
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), controller)["status"] == "REJECTED"


def test_asf_hvr_0833_controller_cutoff_is_validated():
    controller = _controller()
    controller.collection_cutoff_at_utc = None
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), controller)["status"] == "REJECTED"


def test_asf_hvr_0834_controller_stage_is_validated():
    controller = _controller()
    controller.analysis_stage = None
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), controller)["status"] == "REJECTED"


def test_asf_hvr_0835_join_is_paper_only():
    result = economic_freeze_to_controller_boundary_receipt(_freeze(), _controller())
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_asf_hvr_0836_join_never_promotes():
    assert economic_freeze_to_controller_boundary_receipt(_freeze(), _controller())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_0837_join_reports_both_boundaries():
    result = economic_freeze_to_controller_boundary_receipt(_freeze(), _controller())
    assert result["freeze_status"] == "PROVEN"
    assert result["controller_status"] == "PROVEN"


def test_asf_hvr_0838_join_does_not_mutate_controller():
    controller = _controller()
    before = controller.to_dict()
    economic_freeze_to_controller_boundary_receipt(_freeze(), controller)
    assert controller.to_dict() == before


def test_asf_hvr_0839_green_status_without_freeze_is_rejected():
    result = economic_freeze_to_controller_boundary_receipt({"status": "PROVEN"}, _controller())
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True


def test_asf_hvr_0840_green_status_without_controller_is_rejected():
    result = economic_freeze_to_controller_boundary_receipt(_freeze(), {"status": "PROVEN"})
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True
