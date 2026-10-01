from __future__ import annotations

import json

from tools.build_global_implementation_closure import (
    current_analysis_campaign_status,
    digest,
    validate_current_resume_receipt,
)


def _phase():
    return {
        "phase": "ANALYZE",
        "epoch": 3,
        "source_collection_epoch": 2,
        "analysis_stage": "SCOREBOARD",
    }


def _resume_campaign(selection: str = "selection-a"):
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-resume-proof-v1",
        "kind": "replay",
        "creation_phase": "ANALYZE",
        "status": "COMPLETE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "dataset_selection_id": selection,
        "terminal_evidence_digest": "e" * 64,
        "cursor": {
            "resume_proof": True,
            "checkpoint_id": "c" * 64,
        },
    }


def _write_resume_receipt(root, *, selection: str = "selection-a"):
    campaign = _resume_campaign(selection)
    campaign_root = root / "catalog/campaigns"
    campaign_root.mkdir(parents=True, exist_ok=True)
    (campaign_root / f"{campaign['campaign_id']}.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )
    body = {
        "schema": "alina.two_segment_resume_receipt.v2",
        "workflow_run_id": "123",
        "segment_a_job_id": "456",
        "segment_b_job_id": "789",
        "distinct_github_job_ids": True,
        "main_alina_head": "a" * 40,
        "dataset_v2_head": "b" * 40,
        "segment_a_workflow_result": "success",
        "segment_b_workflow_result": "success",
        "campaign_id": campaign["campaign_id"],
        "fresh_runner_for_segment_b": True,
        "runner_filesystem_reused": False,
        "durable_dataset_state_required": True,
        "segment_a_checkpoint_verified": True,
        "segment_a_checkpoint_id": "d" * 64,
        "segment_a_completed_units": 1,
        "terminal_campaign_status": "COMPLETE",
        "terminal_phase_epoch": 3,
        "terminal_source_collection_epoch": 2,
        "terminal_selection_id": selection,
        "terminal_checkpoint_id": campaign["cursor"]["checkpoint_id"],
        "terminal_completed_units": 2,
        "completed_unit_identities": ["0", "1"],
        "duplicate_completed_unit_count": 0,
        "terminal_evidence_digest": campaign["terminal_evidence_digest"],
        "checkpoint_lineage": [{"result_sha256": "d" * 64}],
        "segment_a_operation": "dataset_selection_plan",
        "segment_b_operation": "materialize_replay_selection",
        "resumed_from_durable_checkpoint": True,
        "duplicate_replay_work_count": 0,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = digest(body)
    (root / "catalog/RESUME_SMOKE_RECEIPT.json").write_text(
        json.dumps(body), encoding="utf-8"
    )
    return body


def test_current_resume_receipt_requires_fresh_distinct_jobs_and_exact_epoch(tmp_path):
    receipt = _write_resume_receipt(tmp_path)

    valid, reason, loaded = validate_current_resume_receipt(tmp_path, _phase())

    assert valid is True
    assert reason == "CURRENT_RESUME_RECEIPT_VALID"
    assert loaded["workflow_run_id"] == receipt["workflow_run_id"]


def test_current_resume_receipt_rejects_duplicate_replay_work(tmp_path):
    receipt = _write_resume_receipt(tmp_path)
    receipt["duplicate_replay_work_count"] = 1
    receipt_body = dict(receipt)
    receipt_body.pop("receipt_digest")
    receipt["receipt_digest"] = digest(receipt_body)
    (tmp_path / "catalog/RESUME_SMOKE_RECEIPT.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )

    valid, reason, _ = validate_current_resume_receipt(tmp_path, _phase())

    assert valid is False
    assert reason == "CURRENT_RESUME_DUPLICATE_REPLAY_WORK"


def test_current_resume_receipt_rejects_stale_epoch(tmp_path):
    _write_resume_receipt(tmp_path)
    phase = _phase()
    phase["epoch"] = 4

    valid, reason, _ = validate_current_resume_receipt(tmp_path, phase)

    assert valid is False
    assert reason == "CURRENT_RESUME_PHASE_EPOCH_STALE"


def _campaign(kind: str, *, status: str = "COMPLETE", selection: str = "selection-a"):
    suffix = {
        "replay": "replay-v2",
        "backtest": "backtest-v2",
        "oos": "oos-v2",
        "forward_paper": "forward-paper-v2",
        "module_pnl_proof": "pnl-proof-v2",
        "scoreboard": "scoreboard-v2",
    }[kind]
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": f"analysis-e3-{suffix}",
        "kind": kind,
        "creation_phase": "ANALYZE",
        "status": status,
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "dataset_selection_id": selection,
    }


def test_analysis_closure_requires_all_six_kinds_complete_on_one_selection(tmp_path):
    root = tmp_path / "catalog/campaigns"
    root.mkdir(parents=True)
    kinds = (
        "replay",
        "backtest",
        "oos",
        "forward_paper",
        "module_pnl_proof",
        "scoreboard",
    )
    for row in (_campaign(kind) for kind in kinds):
        (root / f"{row['campaign_id']}.json").write_text(
            json.dumps(row), encoding="utf-8"
        )

    complete, coherent, status = current_analysis_campaign_status(tmp_path, _phase())

    assert complete is True
    assert coherent is True
    assert status["selection_ids"] == ["selection-a"]
    assert all(status["by_kind"][kind]["complete"] for kind in kinds)


def test_analysis_closure_rejects_incomplete_or_selection_drift(tmp_path):
    root = tmp_path / "catalog/campaigns"
    root.mkdir(parents=True)
    rows = [
        _campaign("replay"),
        _campaign("backtest"),
        _campaign("oos"),
        _campaign("forward_paper", selection="selection-b"),
        _campaign("module_pnl_proof"),
        _campaign("scoreboard", status="PENDING"),
    ]
    for row in rows:
        (root / f"{row['campaign_id']}.json").write_text(
            json.dumps(row), encoding="utf-8"
        )

    complete, coherent, status = current_analysis_campaign_status(tmp_path, _phase())

    assert complete is False
    assert coherent is False
    assert status["by_kind"]["scoreboard"]["complete"] is False
    assert status["selection_ids"] == ["selection-a", "selection-b"]
