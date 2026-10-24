from __future__ import annotations

import json
from pathlib import Path
import pytest
from hl_observer.ops import self_hosted_return as returner

FAMILIES = ("copy_vault",)


def _job_result(result_dir: Path, workspace: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "JOB_RESULT.json").write_text(json.dumps({"job_id": "vnext-public-return", "status": "SUCCESS", "suite": "lead-lag-full", "mode": "economic", "project_sha": "a" * 40, "request_digest": "b" * 64, "workspace": str(workspace), "exit_code": 0}), encoding="utf-8")


def test_compact_vnext_summary_is_allowlisted_and_train_only() -> None:
    compact = returner.compact_vnext_summary({"schema_version": "hypersmart.economic_vnext_pack.v1", "selection_scope": "TRAIN_ONLY_PRE_FREEZE", "heldout_evaluated": False, "canonical_campaigns_mutated": False, "families": {"copy_vault": {"status": "CANDIDATE", "selection_eligible": True, "physical_freeze_allowed": True, "freeze_candidate_sha256": "c" * 64, "raw_trades": [{"secret": True}]}, "lead_lag": {"status": "PAUSED", "selection_eligible": True, "physical_freeze_allowed": True, "freeze_candidate_sha256": "d" * 64}}, "lead_source_alignment": {"sources": ["raw-path-must-not-leak"]}, "reports": {"lead_lag": "private/path.json"}, "paper_read_only": True, "real_execution": False})
    assert compact is not None
    assert compact["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert compact["heldout_evaluated"] is False
    assert compact["families"]["copy_vault"]["physical_freeze_allowed"] is True
    assert compact["families"]["copy_vault"]["freeze_candidate_sha256"] == "c" * 64
    assert "raw_trades" not in compact["families"]["copy_vault"]
    assert "lead_lag" not in compact["families"]
    assert "lead_source_alignment" not in compact
    assert "reports" not in compact
    assert compact["paper_read_only"] is True
    assert compact["real_execution"] is False


def test_compact_causal_diagnostic_caps_events_and_hides_book_payloads() -> None:
    events = [{"event_ts_ms": 1_800_000_000_000 + index, "classification": "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF", "next_book_delay_ms": 2_295 + index, "gap_count_delta": 0, "reconnect_count_delta": 0, "explicit_collector_gap": False, "previous_book": {"secret": "raw"}, "next_book": {"secret": "raw"}} for index in range(returner.MAX_DIAGNOSTIC_EVENTS + 7)]
    compact = returner.compact_lead_lag_diagnostic({"schema_version": "hypersmart.lead_lag_causal_gap_diagnostic.v1", "purpose": "DATA_QUALITY_AND_CAUSAL_BOOK_AVAILABILITY_ONLY", "diagnostic_threshold_bps": 8.0, "economic_threshold_bps": 20.0, "economic_parameters_modified": False, "causal_book_availability": {"event_count": len(events), "root_cause": "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF", "max_causal_book_delay_ms": 750, "classification_counts": {"NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF": len(events)}, "events": events}, "paper_read_only": True, "real_execution": False})
    assert compact is not None
    assert compact["event_count"] == len(events)
    assert len(compact["events"]) == returner.MAX_DIAGNOSTIC_EVENTS
    assert compact["events_truncated"] is True
    assert "previous_book" not in compact["events"][0]
    assert "next_book" not in compact["events"][0]
    assert compact["economic_parameters_modified"] is False


def test_build_return_exposes_only_copy_vault_vnext_and_hides_paused_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    campaign_dir = workspace / returner.CAMPAIGN_DIR
    campaign_dir.mkdir(parents=True)
    for family in FAMILIES:
        (campaign_dir / f"{family}.json").write_text("{}", encoding="utf-8")
    vnext_dir = workspace / returner.VNEXT_SUMMARY_RELATIVE.parent
    vnext_dir.mkdir(parents=True, exist_ok=True)
    (workspace / returner.VNEXT_SUMMARY_RELATIVE).write_text(json.dumps({"schema_version": "hypersmart.economic_vnext_pack.v1", "selection_scope": "TRAIN_ONLY_PRE_FREEZE", "heldout_evaluated": False, "canonical_campaigns_mutated": False, "families": {"copy_vault": {"status": "TRAIN_CANDIDATE", "selection_eligible": True, "physical_freeze_allowed": True, "freeze_candidate_sha256": "c" * 64}, "lead_lag": {"status": "TRAIN_CANDIDATE", "selection_eligible": True, "physical_freeze_allowed": True, "freeze_candidate_sha256": "d" * 64}}, "paper_read_only": True, "real_execution": False}), encoding="utf-8")
    result_dir = tmp_path / "result"
    _job_result(result_dir, workspace)
    (result_dir / returner.LEAD_LAG_DIAGNOSTIC_FILENAME).write_text(json.dumps({"diagnostic_threshold_bps": 8.0, "economic_threshold_bps": 20.0, "economic_parameters_modified": False, "causal_book_availability": {"event_count": 2, "root_cause": "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF", "classification_counts": {"NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF": 2}, "events": [{"event_ts_ms": 1, "classification": "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF", "next_book_delay_ms": 2295, "gap_count_delta": 0, "reconnect_count_delta": 0}, {"event_ts_ms": 2, "classification": "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF", "next_book_delay_ms": 4715, "gap_count_delta": 0, "reconnect_count_delta": 0}]}, "paper_read_only": True, "real_execution": False}), encoding="utf-8")
    monkeypatch.setattr(returner, "certify_workspace", lambda root: {"all_families_certified": False, "families": {}})
    monkeypatch.setattr(returner, "build_decision", lambda root: {"next_recommended_job": None})
    payload = returner.build_return(result_dir)
    assert payload["vnext_research"]["families"]["copy_vault"]["selection_eligible"] is True
    assert "lead_lag" not in payload["vnext_research"]["families"]
    assert payload["lead_lag_causal_diagnostic"] is None
    json_path, md_path = returner.write_return(result_dir, payload)
    public = json.loads(json_path.read_text(encoding="utf-8"))
    assert public["vnext_research"]["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert public["lead_lag_causal_diagnostic"] is None
    markdown = md_path.read_text(encoding="utf-8")
    assert "Recherche vNext TRAIN-only" in markdown
    assert "Diagnostic causal Lead-Lag" not in markdown
