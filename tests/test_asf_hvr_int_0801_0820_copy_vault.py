from hl_observer.backtest.walk_forward import walk_forward_safety_receipt
from hl_observer.control_plane.phase_state import (
    AlinaPhaseState,
    walk_forward_to_phase_boundary_receipt,
)


def _phase():
    return AlinaPhaseState(
        phase="ANALYZE",
        epoch=4,
        collection_started_at_utc="2026-01-01T00:00:00Z",
        collection_cutoff_at_utc="2026-01-01T01:00:00Z",
        source_collection_epoch=4,
        analysis_stage="OOS",
    )


def _walk(**overrides):
    result = {
        "train": ["t1"],
        "oos": ["o1"],
        "forward": ["f1"],
        "code_sha": "c" * 64,
        "data_sha": "d" * 64,
        "cutoff_ts_ms": 100,
        "trials": 1,
    }
    result.update(overrides)
    return result


def test_asf_hvr_0801_normal_fixture_joins_safely():
    assert walk_forward_to_phase_boundary_receipt(_walk(), _phase())["status"] == "PROVEN"


def test_asf_hvr_0802_missing_walk_field_fails_closed():
    walk = _walk()
    walk.pop("oos")
    assert walk_forward_to_phase_boundary_receipt(walk, _phase())["status"] == "REJECTED"


def test_asf_hvr_0803_invalid_phase_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(), {"phase": "ANALYZE"})["status"] == "REJECTED"


def test_asf_hvr_0804_invalid_trials_fail_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(trials=0), _phase())["status"] == "REJECTED"


def test_asf_hvr_0805_empty_train_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(train=[]), _phase())["status"] == "REJECTED"


def test_asf_hvr_0806_empty_oos_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(oos=[]), _phase())["status"] == "REJECTED"


def test_asf_hvr_0807_empty_forward_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(forward=[]), _phase())["status"] == "REJECTED"


def test_asf_hvr_0808_future_cutoff_is_rejected_by_walk_gate():
    assert walk_forward_safety_receipt(_walk(cutoff_ts_ms="future"))["status"] == "REJECTED"
    assert walk_forward_to_phase_boundary_receipt(_walk(cutoff_ts_ms=None), _phase())["status"] == "REJECTED"


def test_asf_hvr_0809_missing_code_hash_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(code_sha=None), _phase())["status"] == "REJECTED"


def test_asf_hvr_0810_missing_data_hash_fails_closed():
    assert walk_forward_to_phase_boundary_receipt(_walk(data_sha=None), _phase())["status"] == "REJECTED"


def test_asf_hvr_0811_phase_epoch_is_checked():
    phase = _phase()
    phase.epoch = 0
    assert walk_forward_to_phase_boundary_receipt(_walk(), phase)["status"] == "REJECTED"


def test_asf_hvr_0812_phase_cutoff_is_checked():
    phase = _phase()
    phase.collection_cutoff_at_utc = None
    assert walk_forward_to_phase_boundary_receipt(_walk(), phase)["status"] == "REJECTED"


def test_asf_hvr_0813_phase_stage_is_checked():
    phase = _phase()
    phase.analysis_stage = None
    assert walk_forward_to_phase_boundary_receipt(_walk(), phase)["status"] == "REJECTED"


def test_asf_hvr_0814_walk_sha_mismatch_is_not_normalized():
    assert walk_forward_to_phase_boundary_receipt(_walk(code_sha=""), _phase())["status"] == "REJECTED"


def test_asf_hvr_0815_walk_trials_are_not_defaulted():
    assert walk_forward_to_phase_boundary_receipt(_walk(trials=None), _phase())["status"] == "REJECTED"


def test_asf_hvr_0816_join_is_paper_only():
    result = walk_forward_to_phase_boundary_receipt(_walk(), _phase())
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_asf_hvr_0817_join_never_mutates_phase():
    phase = _phase()
    before = phase.to_dict()
    walk_forward_to_phase_boundary_receipt(_walk(), phase)
    assert phase.to_dict() == before


def test_asf_hvr_0818_join_never_promotes():
    assert walk_forward_to_phase_boundary_receipt(_walk(), _phase())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_0819_join_reports_both_boundaries():
    result = walk_forward_to_phase_boundary_receipt(_walk(), _phase())
    assert result["walk_forward_status"] == "PROVEN"
    assert result["phase_state_status"] == "PROVEN"


def test_asf_hvr_0820_green_status_without_full_boundaries_is_rejected():
    result = walk_forward_to_phase_boundary_receipt({"status": "PROVEN"}, {"status": "PROVEN"})
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True
