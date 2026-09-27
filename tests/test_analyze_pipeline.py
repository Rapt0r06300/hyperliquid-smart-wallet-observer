"""Unit tests for AnalyzePipelineRunner, Capability Gate, and Idea Registry Audit."""
from pathlib import Path
import pytest

from hl_observer.control_plane.phase_controller import PhaseController
from hl_observer.control_plane.capability_gate import (
    verify_venue_capabilities,
    evaluate_dataset_safe_replay_gate,
)
from hl_observer.control_plane.analyze_pipeline import AnalyzePipelineRunner
from hl_observer.event_intelligence.idea_registry_audit import (
    audit_event_intelligence_ideas,
    generate_idea_audit_summary,
)


def test_verify_venue_capabilities():
    res = verify_venue_capabilities()
    assert res["verified"] is True
    assert len(res["unsupported_venues"]) == 0
    assert "hyperliquid" in res["required_venues"]


def test_dataset_safe_replay_gate_pass_and_fail():
    # Valid SAFE outputs
    valid_outputs = [
        {"quality_status": "SAFE", "replay_compatible": True, "evidence_status": "SAFE"}
    ]
    gate_pass = evaluate_dataset_safe_replay_gate("sel-1", valid_outputs)
    assert gate_pass.passed is True
    assert gate_pass.is_safe is True
    assert gate_pass.is_replay_compatible is True

    # Invalid output
    invalid_outputs = [
        {"quality_status": "SAFE", "replay_compatible": False, "evidence_status": "SAFE"}
    ]
    gate_fail = evaluate_dataset_safe_replay_gate("sel-1", invalid_outputs)
    assert gate_fail.passed is False
    assert gate_fail.is_replay_compatible is False


def test_analyze_pipeline_runner_end_to_end(tmp_path: Path):
    state_file = tmp_path / "alina-phase.json"
    ctrl = PhaseController(state_file_path=state_file)
    ctrl.transition_to_collect(request_id="req-c")
    ctrl.transition_to_analyze(request_id="req-a")

    safe_outputs = [
        {"quality_status": "SAFE", "replay_compatible": True, "evidence_status": "SAFE"}
    ]

    runner = AnalyzePipelineRunner(
        phase_controller=ctrl,
        code_sha="a" * 40,
        config_hash="b" * 64,
        outputs_manifest=safe_outputs,
    )

    result = runner.run_pipeline()
    assert result.success is True
    assert result.final_stage == "DONE"
    assert len(result.completed_stages) == 8  # DRAIN through SCOREBOARD
    assert "copy_vault" in result.module_proofs
    assert "lead_lag" in result.module_proofs
    assert "cross_venue_dislocation_v2" in result.module_proofs


def test_idea_registry_audit():
    rows = audit_event_intelligence_ideas()
    assert len(rows) == 120
    summary = generate_idea_audit_summary()
    assert summary["total_ideas_audited"] == 120
    assert "IMPLEMENTED_AND_WIRED" in summary["status_counts"]
