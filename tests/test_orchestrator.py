"""Tests for the ANALYZE phase orchestrator pipeline."""
from __future__ import annotations

import pytest
from hl_observer.control_plane.phase_control import AlinaPhaseState, transition_phase
from hl_observer.control_plane.orchestrator import run_analyze_pipeline


def test_analyze_pipeline_execution(tmp_path):
    p = tmp_path / "alina-phase.json"
    s_collect = transition_phase("COLLECT", p)
    s_analyze = transition_phase("ANALYZE", p)

    mock_evidence = {
        "copy_vault": [{"gross_pnl": 10.0, "fees": 1.0, "slippage": 0.5, "funding_financing": 0.0, "quality_status": "SAFE", "replay_compatible": True}],
        "lead_lag": [{"gross_pnl": 12.0, "fees": 1.0, "slippage": 0.5, "funding_financing": 0.0, "quality_status": "SAFE", "replay_compatible": True}],
        "cross_venue_dislocation_v2": [{"gross_pnl": 8.0, "fees": 0.5, "slippage": 0.5, "funding_financing": 0.0, "quality_status": "SAFE", "replay_compatible": True}],
        "arbitrage": [{"gross_pnl": 15.0, "fees": 1.0, "slippage": 1.0, "funding_financing": 0.0, "quality_status": "SAFE", "replay_compatible": True}],
    }

    receipt = run_analyze_pipeline(s_analyze, mock_evidence)

    assert receipt.current_stage == "DONE"
    assert "PNL_PROOF" in receipt.completed_stages
    assert receipt.all_certified is True
