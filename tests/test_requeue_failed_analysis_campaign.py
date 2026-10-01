from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "requeue_failed_analysis_campaign.py"
SPEC = importlib.util.spec_from_file_location("requeue_failed_analysis_campaign", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest() -> dict:
    return {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-pnl-proof-v2",
        "kind": "module_pnl_proof",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "1" * 40,
        "dataset_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "dataset_generation": "V2_FRESH",
        "config_sha256": "2" * 64,
        "work_plan_sha256": "3" * 64,
        "expires_at": "2026-10-07T00:00:00Z",
        "status": "FAILED",
        "status_reason": "adapter_failed",
        "created_at": "2026-09-30T00:00:00Z",
        "updated_at": "2026-09-30T00:10:00Z",
        "chunk_index": 0,
        "attempts": 0,
        "consecutive_failures": 0,
        "no_progress_count": 0,
        "next_due_at": None,
        "cursor": {"max_shards": 128, "checkpoint_id": "a" * 64, "last_run_id": "123"},
        "completed_units": {"0": {"sha256": "b" * 64, "result": {"status": "FAILED"}}},
        "lease": None,
        "outputs": [],
        "history": [],
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "limits": {
            "max_attempts": 12,
            "max_chunks": 24,
            "max_consecutive_failures": 4,
            "max_no_progress": 3,
            "max_wall_clock_s": 86400,
        },
        "creation_phase": "ANALYZE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
        "dataset_selection_id": "4" * 64,
        "analysis_stage": "PNL_PROOF",
        "operator_request_id": "5" * 64,
        "checkpoint_lineage": [],
        "terminal_evidence_digest": "6" * 64,
    }


def test_requeue_archives_failure_and_resets_only_runtime_state(tmp_path: Path) -> None:
    manifest_path = tmp_path / "catalog" / "campaigns" / "analysis.json"
    history_dir = tmp_path / "catalog" / "campaign-history"
    manifest_path.parent.mkdir(parents=True)
    original = _manifest()
    raw = json.dumps(original, sort_keys=True, indent=2) + "\n"
    manifest_path.write_text(raw, encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=history_dir,
        code_sha="7" * 40,
        config_sha256="8" * 64,
        work_plan_sha256="9" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="PNL_PROOF",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result["requeued"] is True
    archive = Path(result["archive_path"])
    assert archive.is_file()
    assert archive.read_text(encoding="utf-8") == raw
    assert result["archive_sha256"] == hashlib.sha256(raw.encode()).hexdigest()

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["status"] == "PENDING"
    assert updated["status_reason"] == "retry_after_code_fix"
    assert updated["code_sha"] == "7" * 40
    assert updated["phase_epoch"] == 3
    assert updated["source_collection_epoch"] == 2
    assert updated["dataset_selection_id"] == "4" * 64
    assert updated["completed_units"] == {}
    assert updated["terminal_evidence_digest"] is None
    assert updated["lease"] is None
    assert updated["cursor"] == {"max_shards": 128}
    assert updated["history"][-1]["event"] == "retry_after_code_fix"


def test_requeue_is_noop_without_a_new_code_sha(tmp_path: Path) -> None:
    manifest_path = tmp_path / "analysis.json"
    original = _manifest()
    raw = json.dumps(original, sort_keys=True, indent=2) + "\n"
    manifest_path.write_text(raw, encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=tmp_path / "history",
        code_sha="1" * 40,
        config_sha256="2" * 64,
        work_plan_sha256="3" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="PNL_PROOF",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result == {
        "requeued": False,
        "reason": "code_sha_unchanged",
        "status": "FAILED",
        "campaign_id": "analysis-e3-pnl-proof-v2",
    }
    assert manifest_path.read_text(encoding="utf-8") == raw
    assert not (tmp_path / "history").exists()


def test_requeue_refuses_collection_campaigns(tmp_path: Path) -> None:
    manifest_path = tmp_path / "collection.json"
    row = _manifest()
    row["creation_phase"] = "COLLECT"
    row["kind"] = "market_collection"
    row["analysis_stage"] = None
    manifest_path.write_text(json.dumps(row), encoding="utf-8")

    try:
        MODULE.requeue(
            manifest_path=manifest_path,
            history_dir=tmp_path / "history",
            code_sha="7" * 40,
            config_sha256="8" * 64,
            work_plan_sha256="9" * 64,
            expected_phase_epoch=3,
            expected_analysis_stage="PNL_PROOF",
            expected_source_collection_epoch=2,
            expected_dataset_selection_id="4" * 64,
        )
    except SystemExit as exc:
        assert "collection/idle campaigns" in str(exc)
    else:
        raise AssertionError("collection campaign should have been refused")

def test_pending_analysis_without_work_refreshes_to_new_code(tmp_path: Path) -> None:
    manifest_path = tmp_path / "analysis.json"
    row = _manifest()
    row["status"] = "PENDING"
    row["status_reason"] = "retry_after_code_fix"
    row["completed_units"] = {}
    row["checkpoint_lineage"] = []
    row["terminal_evidence_digest"] = None
    row["cursor"] = {"max_shards": 128}
    raw = json.dumps(row, sort_keys=True, indent=2) + "\n"
    manifest_path.write_text(raw, encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=tmp_path / "history",
        code_sha="7" * 40,
        config_sha256="8" * 64,
        work_plan_sha256="9" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="PNL_PROOF",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result["requeued"] is True
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["status"] == "PENDING"
    assert updated["status_reason"] == "refresh_pending_after_code_fix"
    assert updated["code_sha"] == "7" * 40
    assert updated["completed_units"] == {}
    assert updated["lease"] is None
    assert updated["history"][-1]["event"] == "refresh_pending_after_code_fix"
    assert ".pending." in result["archive_path"]


def test_pending_analysis_with_completed_work_is_preserved_without_refresh(tmp_path: Path) -> None:
    manifest_path = tmp_path / "analysis.json"
    row = _manifest()
    row["status"] = "PENDING"
    row["terminal_evidence_digest"] = None
    raw = json.dumps(row, sort_keys=True, indent=2) + "\n"
    manifest_path.write_text(raw, encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=tmp_path / "history",
        code_sha="7" * 40,
        config_sha256="8" * 64,
        work_plan_sha256="9" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="PNL_PROOF",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result == {
        "requeued": False,
        "reason": "pending_durable_work_preserved",
        "status": "PENDING",
        "campaign_id": "analysis-e3-pnl-proof-v2",
    }
    assert manifest_path.read_text(encoding="utf-8") == raw
    assert not (tmp_path / "history").exists()

def test_durable_publication_continuation_refreshes_after_code_fix(tmp_path: Path) -> None:
    manifest_path = tmp_path / "analysis.json"
    row = _manifest()
    row["kind"] = "scoreboard"
    row["analysis_stage"] = "SCOREBOARD"
    row["status"] = "CONTINUATION_REQUIRED"
    row["status_reason"] = "durable_publication_failed"
    row["terminal_evidence_digest"] = None
    row["completed_units"] = {
        "0": {
            "sha256": "a" * 64,
            "result": {
                "status": "FAILED",
                "reason": "durable_publication_failed",
                "previous_status": "COMPLETE",
            },
        }
    }
    raw = json.dumps(row, sort_keys=True, indent=2) + "\n"
    manifest_path.write_text(raw, encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=tmp_path / "history",
        code_sha="7" * 40,
        config_sha256="8" * 64,
        work_plan_sha256="9" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="SCOREBOARD",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result["requeued"] is True
    assert ".continuation_required." in result["archive_path"]
    assert Path(result["archive_path"]).read_text(encoding="utf-8") == raw
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["status"] == "PENDING"
    assert updated["status_reason"] == "retry_after_code_fix"
    assert updated["code_sha"] == "7" * 40
    assert updated["completed_units"] == {}
    assert updated["lease"] is None
    assert updated["cursor"] == {"max_shards": 128}
    assert updated["history"][-1]["event"] == "retry_after_code_fix"


def test_non_publication_continuation_is_not_refreshable(tmp_path: Path) -> None:
    manifest_path = tmp_path / "analysis.json"
    row = _manifest()
    row["status"] = "CONTINUATION_REQUIRED"
    row["status_reason"] = "adapter_timeout"
    manifest_path.write_text(json.dumps(row), encoding="utf-8")

    result = MODULE.requeue(
        manifest_path=manifest_path,
        history_dir=tmp_path / "history",
        code_sha="7" * 40,
        config_sha256="8" * 64,
        work_plan_sha256="9" * 64,
        expected_phase_epoch=3,
        expected_analysis_stage="PNL_PROOF",
        expected_source_collection_epoch=2,
        expected_dataset_selection_id="4" * 64,
    )

    assert result["requeued"] is False
    assert result["reason"] == "status_not_refreshable"
    assert result["status"] == "CONTINUATION_REQUIRED"

