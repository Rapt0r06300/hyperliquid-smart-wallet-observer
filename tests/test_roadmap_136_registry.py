from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.roadmap_136_registry import ROADMAP_SOURCE_SHA256, ROADMAP_TASKS, ROADMAP_ID, STATUSES
from tools.verify_roadmap_136 import build_report


def test_registry_contains_exactly_136_tasks() -> None:
    assert len(ROADMAP_TASKS) == 136
    assert [task.task_id for task in ROADMAP_TASKS] == [f"T{index:03d}" for index in range(1, 137)]
    assert all(task.weight > 0 for task in ROADMAP_TASKS)
    assert ROADMAP_ID == "ALINA_SMART_FLOW_136"
    assert len(ROADMAP_SOURCE_SHA256) == 64


def test_report_is_fail_closed_without_receipts(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    assert report["progress"]["total_weight"] == 136.0
    assert report["progress"]["verified_done_weight"] == 0.0
    assert report["progress"]["implementation_percent"] == 0.0
    assert report["counts"]["TODO"] == 136
    assert report["policy"]["agiflow_used"] is False
    assert report["policy"]["synthetic_evidence_accepted"] is False


def test_invalid_receipt_does_not_promote_task(tmp_path: Path) -> None:
    (tmp_path / "T001-invalid.json").write_text(
        json.dumps({"task_id": "T001", "status": "VERIFIED_DONE"}),
        encoding="utf-8",
    )
    report = build_report(tmp_path)
    assert report["tasks"][0]["status"] == "TODO"
    assert report["progress"]["implementation_percent"] == 0.0


def test_status_taxonomy_excludes_implicit_done() -> None:
    assert "DONE" not in STATUSES
    assert "VERIFIED_DONE" in STATUSES

