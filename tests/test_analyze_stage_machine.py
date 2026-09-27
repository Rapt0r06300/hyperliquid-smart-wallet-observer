"""Unit tests for AnalyzeStageMachine (Block 10 of spec)."""
import pytest

from hl_observer.control_plane.analyze_stage_machine import (
    AnalyzeStageMachine,
    StageReceipt,
    ANALYZE_STAGES,
)


def test_stage_machine_initial_state():
    sm = AnalyzeStageMachine(
        source_collection_epoch=2,
        dataset_selection_id="ds-100",
        code_sha="a" * 40,
        config_hash="b" * 64,
    )
    assert sm.current_stage == "DRAIN"


def test_stage_machine_sequential_progression():
    sm = AnalyzeStageMachine(
        source_collection_epoch=2,
        dataset_selection_id="ds-100",
        code_sha="a" * 40,
        config_hash="b" * 64,
    )

    r_drain = sm.record_stage_completion(
        stage="DRAIN",
        output_artifact_hashes={"frozen_selection": "hash-1"},
        started_at_utc="2026-09-27T00:00:00Z",
    )
    assert r_drain.stage == "DRAIN"
    assert sm.current_stage == "QUALITY"

    r_quality = sm.record_stage_completion(
        stage="QUALITY",
        output_artifact_hashes={"quality_report": "hash-2"},
        started_at_utc="2026-09-27T00:10:00Z",
    )
    assert sm.current_stage == "REPLAY"


def test_stage_machine_out_of_sequence_rejected():
    sm = AnalyzeStageMachine(
        source_collection_epoch=2,
        dataset_selection_id="ds-100",
        code_sha="a" * 40,
        config_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="expected next stage is 'DRAIN'"):
        sm.record_stage_completion(
            stage="REPLAY",
            output_artifact_hashes={"replay_log": "hash-x"},
            started_at_utc="2026-09-27T00:00:00Z",
        )


def test_stage_machine_failure_record():
    sm = AnalyzeStageMachine(
        source_collection_epoch=2,
        dataset_selection_id="ds-100",
        code_sha="a" * 40,
        config_hash="b" * 64,
    )

    rf = sm.record_stage_failure(
        stage="DRAIN",
        failure_reason="timeout_waiting_for_units",
        started_at_utc="2026-09-27T00:00:00Z",
    )
    assert rf.status == "FAILED"
    assert rf.failure_reason == "timeout_waiting_for_units"
