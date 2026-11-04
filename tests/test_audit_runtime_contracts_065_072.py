from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hl_observer.ops.runtime_contract import (
    campaign_diagnostic_receipt,
    capability_runtime_receipt,
    ci_terminal_gate_receipt,
    copy_vault_coverage_receipt,
    global_closure_receipt,
    global_trade_dedup_receipt,
    hosted_resume_receipt,
    scoreboard_terminal_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_global_trade_dedup_reconciles_all_partitions():
    partitions = [
        {"coverage_complete": True, "sha256": "a" * 64, "trade_ids": ["t-1", "t-2"]},
        {"coverage_complete": True, "sha256": "b" * 64, "trade_ids": ["t-3"]},
    ]
    assert global_trade_dedup_receipt(partitions)["status"] == "PROVEN"
    partitions[1]["trade_ids"] = ["t-2"]
    assert global_trade_dedup_receipt(partitions)["status"] == "UNKNOWN"


def test_global_closure_gate_never_turns_partial_report_into_closed():
    report = json.loads((ROOT / "docs/alina-closure-report.json").read_text(encoding="utf-8"))
    assert global_closure_receipt(report)["status"] == "UNKNOWN"
    complete = {
        "status": "CLOSED",
        "coverage_complete": True,
        "index_sha256": "c" * 64,
        "receipt_digest": "d" * 64,
        "total_tasks": 2,
        "verified_tasks": 2,
    }
    assert global_closure_receipt(complete)["status"] == "PROVEN"


def test_copy_vault_coverage_requires_every_lane():
    lanes = [
        {
            "family": "copy_vault",
            "status": "PROVEN",
            "replay_compatible": True,
            "shards": 2,
            "source_sha256": "e" * 64,
        },
        {
            "family": "copy_vault",
            "status": "PROVEN",
            "replay_compatible": True,
            "shards": 1,
            "source_sha256": "f" * 64,
        },
    ]
    assert copy_vault_coverage_receipt(lanes)["status"] == "PROVEN"
    lanes[1]["replay_compatible"] = False
    assert copy_vault_coverage_receipt(lanes)["status"] == "UNKNOWN"


def test_two_hosted_resumes_share_exact_sha_and_persisted_state():
    runs = [
        {
            "run_id": "1001",
            "runner_kind": "github-hosted",
            "status": "COMPLETED",
            "code_sha": "1" * 40,
            "persisted_state_sha256": "2" * 64,
            "artifact": "resume-1001.tgz",
        },
        {
            "run_id": "1002",
            "runner_kind": "github-hosted",
            "status": "COMPLETED",
            "code_sha": "1" * 40,
            "persisted_state_sha256": "2" * 64,
            "artifact": "resume-1002.tgz",
        },
    ]
    assert hosted_resume_receipt(runs, expected_code_sha="1" * 40)["status"] == "PROVEN"
    runs[1]["code_sha"] = "3" * 40
    assert hosted_resume_receipt(runs, expected_code_sha="1" * 40)["status"] == "UNKNOWN"


def test_scoreboard_terminal_requires_manual_paper_gate():
    payload = {
        "phase": "DONE",
        "manual_order_ack": True,
        "execution_enabled": False,
        "current_epoch": 8,
        "archived_epoch": 7,
    }
    assert scoreboard_terminal_receipt(payload)["status"] == "PROVEN"
    payload["execution_enabled"] = True
    assert scoreboard_terminal_receipt(payload)["status"] == "UNKNOWN"


def test_ci_gate_distinguishes_superseded_cancel_from_unknown_cancel():
    assert ci_terminal_gate_receipt(
        {"status": "CANCELLED", "superseded_by_newer_sha": True}
    )["status"] == "EXPECTED_CANCELLED"
    assert ci_terminal_gate_receipt(
        {"status": "CANCELLED", "superseded_by_newer_sha": False}
    )["status"] == "UNKNOWN"
    assert ci_terminal_gate_receipt(
        {
            "status": "COMPLETED",
            "conclusion": "success",
            "head_stable": True,
            "terminal_gate": True,
            "head_sha": "4" * 40,
        }
    )["status"] == "PROVEN"


def test_campaign_diagnostics_expose_reason_file_and_epoch():
    result = campaign_diagnostic_receipt(
        manifest_path="broken.json", reason_code="JSONDecodeError", phase_epoch=3
    )
    assert result == {
        "status": "PROVEN",
        "manifest_path": "broken.json",
        "reason_code": "JSONDecodeError",
        "phase_epoch": 3,
    }


def test_cli_invalid_campaign_diagnostic_is_structured(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "tools/resumable_campaign.py", "list-due", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    line = next(line for line in result.stderr.splitlines() if line.startswith("invalid_campaign="))
    diagnostic = json.loads(line.split("=", 1)[1])
    assert diagnostic["manifest_path"] == "broken.json"
    assert diagnostic["reason_code"] == "JSONDecodeError"
    assert "phase_epoch" in diagnostic


def test_capability_health_is_bound_to_current_hosted_sha():
    payload = {
        "github_sha": "5" * 40,
        "runner_kind": "github-hosted",
        "paper_read_only": True,
        "real_execution": False,
        "receipt_digest": "6" * 64,
        "generated_at_utc": "2026-11-04T00:00:00Z",
        "schema_version": "alina.source_capability_runtime.v1",
    }
    assert capability_runtime_receipt(payload, expected_sha="5" * 40)["status"] == "PROVEN"
    assert capability_runtime_receipt(payload, expected_sha="7" * 40)["status"] == "UNKNOWN"
