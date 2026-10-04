from __future__ import annotations

import json
from pathlib import Path

from tools.collect_resume_probe import build_receipt, segment_a, segment_b


def _write_phase(root: Path, epoch: int = 6) -> None:
    control = root / "control"
    control.mkdir(parents=True, exist_ok=True)
    (control / "alina-phase.json").write_text(
        json.dumps({
            "phase": "COLLECT",
            "epoch": epoch,
            "requested_at_utc": "2026-10-01T04:50:49Z",
            "collection_started_at_utc": "2026-10-01T04:50:49Z",
            "collection_cutoff_at_utc": None,
            "source_collection_epoch": None,
            "analysis_stage": None,
        }),
        encoding="utf-8",
    )


def test_collect_resume_probe_uses_two_durable_units_without_network(tmp_path: Path):
    _write_phase(tmp_path)
    state = Path("catalog/COLLECT_RESUME_PROBE_STATE.json")

    first = segment_a(
        tmp_path,
        state,
        owner_run_id="run-a",
        workflow_run_id="123",
        code_sha="a" * 40,
    )
    assert first["status"] == "CONTINUATION_REQUIRED"
    assert len(first["completed_units"]) == 1
    assert first["cursor"]["network_used"] is False

    second = segment_b(tmp_path, state, owner_run_id="run-b")
    assert second["status"] == "COMPLETE"
    assert len(second["completed_units"]) == 2
    assert len(second["checkpoint_lineage"]) >= 1
    assert all(
        unit["result"]["network_used"] is False
        for unit in second["completed_units"].values()
    )


def test_collect_resume_receipt_binds_current_control_plane_files(tmp_path: Path):
    _write_phase(tmp_path)
    state = Path("catalog/COLLECT_RESUME_PROBE_STATE.json")
    segment_a(
        tmp_path,
        state,
        owner_run_id="run-a",
        workflow_run_id="123",
        code_sha="a" * 40,
    )
    segment_b(tmp_path, state, owner_run_id="run-b")

    control_paths = ("a.py", "b.py", "workflow.yml")
    for rel in control_paths:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel, encoding="utf-8")

    receipt = build_receipt(
        tmp_path,
        state,
        Path("catalog/COLLECT_RESUME_SMOKE_RECEIPT.json"),
        workflow_run_id="123",
        segment_a_job_id="456",
        segment_b_job_id="789",
        control_paths=control_paths,
    )
    assert receipt["schema"] == "alina.two_segment_resume_receipt.v3"
    assert receipt["distinct_github_job_ids"] is True
    assert receipt["fresh_runner_for_segment_b"] is True
    assert receipt["resumed_from_durable_checkpoint"] is True
    assert receipt["network_used"] is False
    assert receipt["replay_run"] is False
    assert receipt["backtest_run"] is False
