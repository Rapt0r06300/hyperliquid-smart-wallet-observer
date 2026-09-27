"""Unit tests for Phase State and Phase Controller (Block 1 & 2 of spec)."""
import json
from pathlib import Path
import pytest

from hl_observer.control_plane.phase_state import (
    AlinaPhaseState,
    validate_phase_state,
    parse_iso_utc,
)
from hl_observer.control_plane.phase_controller import PhaseController


def test_valid_idle_state_parse():
    data = {
        "schema_version": 1,
        "phase": "IDLE",
        "epoch": 1,
        "requested_at_utc": "2026-09-27T00:00:00Z",
        "collection_started_at_utc": None,
        "collection_cutoff_at_utc": None,
        "source_collection_epoch": None,
        "analysis_stage": None,
        "requested_by": "operator",
        "request_id": None,
    }
    state = AlinaPhaseState.from_dict(data)
    assert state.phase == "IDLE"
    assert state.epoch == 1


def test_invalid_phase_rejects():
    data = {
        "schema_version": 1,
        "phase": "INVALID_PHASE",
        "epoch": 1,
        "requested_at_utc": "2026-09-27T00:00:00Z",
        "requested_by": "operator",
    }
    with pytest.raises(ValueError, match="Invalid phase"):
        AlinaPhaseState.from_dict(data)


def test_non_positive_epoch_rejects():
    data = {
        "schema_version": 1,
        "phase": "IDLE",
        "epoch": 0,
        "requested_at_utc": "2026-09-27T00:00:00Z",
        "requested_by": "operator",
    }
    with pytest.raises(ValueError, match="Epoch must be positive integer"):
        AlinaPhaseState.from_dict(data)


def test_invalid_timestamp_tz_rejects():
    data = {
        "schema_version": 1,
        "phase": "IDLE",
        "epoch": 1,
        "requested_at_utc": "2026-09-27T00:00:00+02:00",
        "requested_by": "operator",
    }
    with pytest.raises(ValueError, match="must be UTC ISO-8601 ending in Z"):
        AlinaPhaseState.from_dict(data)


def test_analyze_without_source_epoch_rejects():
    data = {
        "schema_version": 1,
        "phase": "ANALYZE",
        "epoch": 2,
        "requested_at_utc": "2026-09-27T00:00:00Z",
        "collection_started_at_utc": "2026-09-27T00:00:00Z",
        "collection_cutoff_at_utc": "2026-09-27T01:00:00Z",
        "source_collection_epoch": None,
        "analysis_stage": "DRAIN",
        "requested_by": "operator",
    }
    with pytest.raises(ValueError, match="ANALYZE phase requires a valid positive integer source_collection_epoch"):
        AlinaPhaseState.from_dict(data)


def test_collect_with_analysis_fields_rejects():
    data = {
        "schema_version": 1,
        "phase": "COLLECT",
        "epoch": 1,
        "requested_at_utc": "2026-09-27T00:00:00Z",
        "collection_started_at_utc": "2026-09-27T00:00:00Z",
        "collection_cutoff_at_utc": "2026-09-27T01:00:00Z",
        "source_collection_epoch": None,
        "analysis_stage": None,
        "requested_by": "operator",
    }
    with pytest.raises(ValueError, match="COLLECT phase must have null collection_cutoff_at_utc"):
        AlinaPhaseState.from_dict(data)


def test_phase_controller_transitions(tmp_path: Path):
    state_file = tmp_path / "alina-phase.json"
    ctrl = PhaseController(state_file_path=state_file)
    assert ctrl.current_state.phase == "IDLE"
    assert ctrl.current_state.epoch == 1

    # IDLE -> COLLECT
    r1 = ctrl.transition_to_collect(request_id="req-1", now_utc="2026-09-27T01:00:00Z")
    assert r1.previous_epoch == 1
    assert r1.new_epoch == 2
    assert ctrl.current_state.phase == "COLLECT"
    assert ctrl.current_state.collection_started_at_utc == "2026-09-27T01:00:00Z"

    # Duplicate COLLECT request is idempotent
    r1_dup = ctrl.transition_to_collect(request_id="req-1", now_utc="2026-09-27T01:05:00Z")
    assert r1_dup.new_epoch == 2
    assert ctrl.current_state.epoch == 2

    # COLLECT -> ANALYZE
    r2 = ctrl.transition_to_analyze(request_id="req-2", initial_stage="DRAIN", now_utc="2026-09-27T02:00:00Z")
    assert r2.previous_epoch == 2
    assert r2.new_epoch == 3
    assert ctrl.current_state.phase == "ANALYZE"
    assert ctrl.current_state.source_collection_epoch == 2
    assert ctrl.current_state.collection_cutoff_at_utc == "2026-09-27T02:00:00Z"
    assert ctrl.current_state.analysis_stage == "DRAIN"

    # Direct IDLE -> ANALYZE is illegal
    ctrl2 = PhaseController(state_file_path=tmp_path / "idle.json")
    with pytest.raises(ValueError, match="Transition to ANALYZE requires phase COLLECT"):
        ctrl2.transition_to_analyze(request_id="req-3")


def test_advance_analysis_stage(tmp_path: Path):
    ctrl = PhaseController(state_file_path=tmp_path / "alina-phase.json")
    ctrl.transition_to_collect(request_id="req-1")
    ctrl.transition_to_analyze(request_id="req-2")

    assert ctrl.current_state.analysis_stage == "DRAIN"
    ctrl.advance_analysis_stage("QUALITY")
    assert ctrl.current_state.analysis_stage == "QUALITY"

    ctrl.advance_analysis_stage("DONE")
    assert ctrl.current_state.analysis_stage == "DONE"
    # Phase remains ANALYZE until operator sets IDLE
    assert ctrl.current_state.phase == "ANALYZE"
