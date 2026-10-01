#!/usr/bin/env python3
"""Build the fail-closed cross-repository implementation closure receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ANALYSIS_KINDS = (
    "replay",
    "backtest",
    "oos",
    "forward_paper",
    "module_pnl_proof",
    "scoreboard",
)


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_frozen_coverage_receipt(
    dataset: Path,
    phase: Mapping[str, Any],
    expected_selection_id: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    receipt = load(dataset / "catalog/ANALYSIS_FROZEN_COVERAGE_RECEIPT.json", {})
    if not isinstance(receipt, dict) or receipt.get("schema") != "alina.analysis_frozen_coverage_receipt.v1":
        return False, "FROZEN_COVERAGE_RECEIPT_MISSING", {}
    stored_digest = str(receipt.get("receipt_digest") or "")
    body = dict(receipt)
    body.pop("receipt_digest", None)
    if len(stored_digest) != 64 or digest(body) != stored_digest:
        return False, "FROZEN_COVERAGE_RECEIPT_DIGEST_INVALID", receipt
    bindings = (
        ("phase_epoch", phase.get("epoch")),
        ("source_collection_epoch", phase.get("source_collection_epoch")),
        ("collection_cutoff_at_utc", phase.get("collection_cutoff_at_utc")),
    )
    for key, expected in bindings:
        if receipt.get(key) != expected:
            return False, f"FROZEN_COVERAGE_BINDING_MISMATCH:{key}", receipt
    if expected_selection_id and receipt.get("dataset_selection_id") != expected_selection_id:
        return False, "FROZEN_COVERAGE_SELECTION_MISMATCH", receipt
    if (
        receipt.get("paper_only") is not True
        or receipt.get("read_only") is not True
        or receipt.get("real_execution") is not False
    ):
        return False, "FROZEN_COVERAGE_NOT_PAPER_ONLY", receipt
    coverage = receipt.get("coverage")
    required = (
        "valid_record_count_exact",
        "unique_record_count_exact",
        "trade_count_exact",
        "unique_trade_count_exact",
        "uncompressed_bytes_exact",
    )
    if not isinstance(coverage, dict) or not all(coverage.get(key) is True for key in required):
        return False, "FROZEN_COVERAGE_NOT_EXACT", receipt
    if not isinstance(receipt.get("replayable_shards"), int) or receipt["replayable_shards"] < 1:
        return False, "FROZEN_COVERAGE_NOT_REPLAYABLE", receipt
    return True, "FROZEN_COVERAGE_RECEIPT_VALID", receipt


def validate_current_scoreboard_receipt(
    dataset: Path,
    phase: Mapping[str, Any],
) -> tuple[bool, dict[str, Any], str, dict[str, Any]]:
    receipt = load(dataset / "catalog/ANALYSIS_SCOREBOARD_RECEIPT.json", {})
    if not isinstance(receipt, dict) or receipt.get("schema") != "alina.analysis_scoreboard_receipt.v1":
        return False, {}, "CURRENT_SCOREBOARD_RECEIPT_MISSING", {}

    stored_receipt_digest = str(receipt.get("receipt_digest") or "")
    receipt_body = dict(receipt)
    receipt_body.pop("receipt_digest", None)
    if len(stored_receipt_digest) != 64 or digest(receipt_body) != stored_receipt_digest:
        return False, {}, "CURRENT_SCOREBOARD_RECEIPT_DIGEST_INVALID", receipt

    scoreboard = receipt.get("scoreboard")
    if not isinstance(scoreboard, dict):
        return False, {}, "CURRENT_SCOREBOARD_PAYLOAD_MISSING", receipt
    if scoreboard.get("schema_version") != "hypersmart.economic_family_scoreboards.v2":
        return False, {}, "CURRENT_SCOREBOARD_SCHEMA_INVALID", receipt
    if digest(scoreboard) != str(receipt.get("scoreboard_sha256") or ""):
        return False, {}, "CURRENT_SCOREBOARD_HASH_MISMATCH", receipt
    if scoreboard.get("paper_read_only") is not True or scoreboard.get("real_execution") is not False:
        return False, {}, "CURRENT_SCOREBOARD_NOT_PAPER_ONLY", receipt

    campaign_id = str(receipt.get("campaign_id") or "")
    if not campaign_id:
        return False, {}, "CURRENT_SCOREBOARD_CAMPAIGN_MISSING", receipt
    campaign = load(dataset / "catalog/campaigns" / f"{campaign_id}.json", {})
    if not isinstance(campaign, dict):
        return False, {}, "CURRENT_SCOREBOARD_CAMPAIGN_NOT_FOUND", receipt
    if (
        campaign.get("schema_version") != "alina.resumable_campaign.v2"
        or campaign.get("kind") != "scoreboard"
        or campaign.get("creation_phase") != "ANALYZE"
        or campaign.get("status") != "COMPLETE"
    ):
        return False, {}, "CURRENT_SCOREBOARD_CAMPAIGN_NOT_COMPLETE", receipt

    binding_pairs = (
        ("phase_epoch", phase.get("epoch")),
        ("source_collection_epoch", phase.get("source_collection_epoch")),
        ("dataset_selection_id", campaign.get("dataset_selection_id")),
        ("collection_cutoff_at_utc", campaign.get("collection_cutoff_at_utc")),
        ("code_sha", campaign.get("code_sha")),
    )
    for key, expected in binding_pairs:
        if receipt.get(key) != expected:
            return False, {}, f"CURRENT_SCOREBOARD_BINDING_MISMATCH:{key}", receipt

    if campaign.get("phase_epoch") != phase.get("epoch"):
        return False, {}, "CURRENT_SCOREBOARD_PHASE_EPOCH_STALE", receipt
    if campaign.get("source_collection_epoch") != phase.get("source_collection_epoch"):
        return False, {}, "CURRENT_SCOREBOARD_SOURCE_EPOCH_STALE", receipt
    if not receipt.get("evidence_tag") or not receipt.get("evidence_repository"):
        return False, {}, "CURRENT_SCOREBOARD_DURABLE_EVIDENCE_MISSING", receipt
    environment_provenance = receipt.get("environment_provenance")
    environment_receipt_sha256 = str(receipt.get("environment_receipt_sha256") or "")
    if not isinstance(environment_provenance, Mapping) or not environment_provenance:
        return False, {}, "CURRENT_SCOREBOARD_ENVIRONMENT_PROVENANCE_MISSING", receipt
    if len(environment_receipt_sha256) != 64:
        return False, {}, "CURRENT_SCOREBOARD_ENVIRONMENT_HASH_MISSING", receipt
    if receipt.get("paper_only") is not True or receipt.get("read_only") is not True or receipt.get("real_execution") is not False:
        return False, {}, "CURRENT_SCOREBOARD_RECEIPT_SAFETY_INVALID", receipt
    return True, scoreboard, "CURRENT_SCOREBOARD_RECEIPT_VALID", receipt


def validate_current_resume_receipt(
    dataset: Path,
    phase: Mapping[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    receipt = load(dataset / "catalog/RESUME_SMOKE_RECEIPT.json", {})
    if not isinstance(receipt, dict) or receipt.get("schema") != "alina.two_segment_resume_receipt.v2":
        return False, "CURRENT_RESUME_RECEIPT_MISSING", {}

    stored_digest = str(receipt.get("receipt_digest") or "")
    receipt_body = dict(receipt)
    receipt_body.pop("receipt_digest", None)
    if len(stored_digest) != 64 or digest(receipt_body) != stored_digest:
        return False, "CURRENT_RESUME_RECEIPT_DIGEST_INVALID", receipt

    required_true = (
        "distinct_github_job_ids",
        "fresh_runner_for_segment_b",
        "durable_dataset_state_required",
        "segment_a_checkpoint_verified",
        "resumed_from_durable_checkpoint",
        "paper_only",
        "read_only",
    )
    if any(receipt.get(key) is not True for key in required_true):
        return False, "CURRENT_RESUME_INVARIANT_MISSING", receipt
    if receipt.get("runner_filesystem_reused") is not False or receipt.get("real_execution") is not False:
        return False, "CURRENT_RESUME_SAFETY_INVALID", receipt
    if (
        receipt.get("segment_a_workflow_result") != "success"
        or receipt.get("segment_b_workflow_result") != "success"
        or receipt.get("terminal_campaign_status") != "COMPLETE"
    ):
        return False, "CURRENT_RESUME_SEGMENT_NOT_COMPLETE", receipt
    if int(receipt.get("terminal_completed_units") or 0) < 2:
        return False, "CURRENT_RESUME_TOO_FEW_UNITS", receipt
    if int(receipt.get("duplicate_completed_unit_count") or 0) != 0:
        return False, "CURRENT_RESUME_DUPLICATE_COMPLETED_UNIT", receipt
    if int(receipt.get("duplicate_replay_work_count") or 0) != 0:
        return False, "CURRENT_RESUME_DUPLICATE_REPLAY_WORK", receipt

    segment_a_job = str(receipt.get("segment_a_job_id") or "")
    segment_b_job = str(receipt.get("segment_b_job_id") or "")
    workflow_run_id = str(receipt.get("workflow_run_id") or "")
    if not workflow_run_id or not segment_a_job or not segment_b_job or segment_a_job == segment_b_job:
        return False, "CURRENT_RESUME_JOB_IDENTITY_INVALID", receipt

    campaign_id = str(receipt.get("campaign_id") or "")
    if not campaign_id:
        return False, "CURRENT_RESUME_CAMPAIGN_MISSING", receipt
    campaign = load(dataset / "catalog/campaigns" / f"{campaign_id}.json", {})
    if not isinstance(campaign, dict):
        return False, "CURRENT_RESUME_CAMPAIGN_NOT_FOUND", receipt
    cursor = campaign.get("cursor") if isinstance(campaign.get("cursor"), dict) else {}
    if (
        campaign.get("schema_version") != "alina.resumable_campaign.v2"
        or campaign.get("kind") != "replay"
        or campaign.get("creation_phase") != "ANALYZE"
        or campaign.get("status") != "COMPLETE"
        or cursor.get("resume_proof") is not True
    ):
        return False, "CURRENT_RESUME_CAMPAIGN_NOT_COMPLETE", receipt

    if campaign.get("phase_epoch") != phase.get("epoch"):
        return False, "CURRENT_RESUME_PHASE_EPOCH_STALE", receipt
    if campaign.get("source_collection_epoch") != phase.get("source_collection_epoch"):
        return False, "CURRENT_RESUME_SOURCE_EPOCH_STALE", receipt
    if receipt.get("terminal_phase_epoch") != phase.get("epoch"):
        return False, "CURRENT_RESUME_RECEIPT_PHASE_EPOCH_STALE", receipt
    if receipt.get("terminal_source_collection_epoch") != phase.get("source_collection_epoch"):
        return False, "CURRENT_RESUME_RECEIPT_SOURCE_EPOCH_STALE", receipt
    if receipt.get("terminal_selection_id") != campaign.get("dataset_selection_id"):
        return False, "CURRENT_RESUME_SELECTION_MISMATCH", receipt
    if receipt.get("terminal_checkpoint_id") != cursor.get("checkpoint_id"):
        return False, "CURRENT_RESUME_CHECKPOINT_MISMATCH", receipt
    if receipt.get("terminal_evidence_digest") != campaign.get("terminal_evidence_digest"):
        return False, "CURRENT_RESUME_EVIDENCE_DIGEST_MISMATCH", receipt

    return True, "CURRENT_RESUME_RECEIPT_VALID", receipt


def _superseded_campaign_ids(rows):
    """Return explicitly superseded attempts only when replacement identity is exact."""
    by_id = {
        str(row.get("campaign_id")): row
        for row in rows
        if row.get("campaign_id")
    }
    identity_fields = (
        "creation_phase",
        "phase_epoch",
        "source_collection_epoch",
        "kind",
        "dataset_selection_id",
        "collection_cutoff_at_utc",
        "work_plan_sha256",
        "config_sha256",
    )
    superseded = set()
    for replacement in rows:
        if replacement.get("status") != "COMPLETE":
            continue
        declared = replacement.get("supersedes_campaign_ids")
        if not isinstance(declared, list):
            continue
        for campaign_id in declared:
            original = by_id.get(str(campaign_id))
            if not isinstance(original, dict):
                continue
            if all(original.get(key) == replacement.get(key) for key in identity_fields):
                superseded.add(str(campaign_id))
    return superseded


def current_analysis_campaign_status(
    dataset: Path,
    phase: Mapping[str, Any],
) -> tuple[bool, bool, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((dataset / "catalog/campaigns").glob("*.json")):
        row = load(path, None)
        if (
            isinstance(row, dict)
            and row.get("schema_version") == "alina.resumable_campaign.v2"
            and row.get("creation_phase") == "ANALYZE"
            and row.get("phase_epoch") == phase.get("epoch")
            and row.get("source_collection_epoch") == phase.get("source_collection_epoch")
            and row.get("kind") in ANALYSIS_KINDS
        ):
            rows.append(row)

    superseded = _superseded_campaign_ids(rows)
    effective_rows = [
        row for row in rows
        if str(row.get("campaign_id") or "") not in superseded
    ]

    by_kind: dict[str, Any] = {}
    for kind in ANALYSIS_KINDS:
        scoped = [row for row in effective_rows if row.get("kind") == kind]
        by_kind[kind] = {
            "campaign_ids": sorted(str(row.get("campaign_id") or "") for row in scoped),
            "states": sorted(str(row.get("status") or "") for row in scoped),
            "complete": bool(scoped) and all(row.get("status") == "COMPLETE" for row in scoped),
        }

    selection_ids = sorted({
        str(row.get("dataset_selection_id"))
        for row in effective_rows
        if row.get("dataset_selection_id")
    })
    all_have_selection = bool(effective_rows) and all(
        bool(row.get("dataset_selection_id")) for row in effective_rows
    )
    selection_coherent = all_have_selection and len(selection_ids) == 1
    all_complete = all(by_kind[kind]["complete"] for kind in ANALYSIS_KINDS)
    return all_complete, selection_coherent, {
        "required_kinds": list(ANALYSIS_KINDS),
        "campaign_count": len(effective_rows),
        "superseded_campaign_ids": sorted(superseded),
        "selection_ids": selection_ids,
        "selection_coherent": selection_coherent,
        "complete": all_complete,
        "by_kind": by_kind,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alina-root", required=True)
    parser.add_argument("--dataset-root", default=".")
    parser.add_argument("--output", default="catalog/GLOBAL_IMPLEMENTATION_CLOSURE.json")
    args = parser.parse_args()
    alina = Path(args.alina_root)
    dataset = Path(args.dataset_root)
    phase = load(dataset / "control/alina-phase.json", {})
    metrics = load(dataset / "catalog/DATA_METRICS.json", {})
    watchdog = load(dataset / "catalog/CAMPAIGN_WATCHDOG_RECEIPT.json", {})
    resilience = load(dataset / "catalog/CAMPAIGN_RESILIENCE_RECEIPT.json", {})
    health = load(dataset / "catalog/DATASET_HEALTH_RECEIPT.json", {})
    phase_map = phase if isinstance(phase, dict) else {}
    scoreboard_valid, scoreboard, scoreboard_reason, scoreboard_receipt = (
        validate_current_scoreboard_receipt(dataset, phase_map)
    )
    resume_valid, resume_reason, resume_receipt = validate_current_resume_receipt(
        dataset, phase_map
    )
    analysis_complete, analysis_selection_coherent, analysis_campaigns = (
        current_analysis_campaign_status(dataset, phase_map)
    )
    improvement_ledger = load(dataset / "catalog/ECONOMIC_IMPROVEMENT_LEDGER.json", {})
    event_status = load(alina / "docs/event-intelligence-120-status.json", {})
    event_summary = event_status.get("summary") if isinstance(event_status, dict) else {}

    families = {}
    scoreboard_families = scoreboard.get("families") if scoreboard_valid else {}
    if not isinstance(scoreboard_families, dict):
        scoreboard_families = {}
    source_names = {
        "copy_vault": "copy_vault",
        "lead_lag": "lead_lag",
        "cross_venue_dislocation": "cross_venue_dislocation_v2",
    }
    for family, source_name in source_names.items():
        source = scoreboard_families.get(source_name)
        if not isinstance(source, dict):
            state, reason = "UNMEASURABLE", scoreboard_reason
        elif source.get("verdict") == "KILL":
            state, reason = "KILL", "ECONOMIC_GATE_REJECTED"
        elif source.get("verdict") == "PROMOTE":
            state, reason = "PROVEN", "PREUVE_ECONOMIQUE_VALIDE"
        else:
            state, reason = "MORE_DATA", ",".join(
                source.get("verdict_reasons")
                or ["MORE_DATA"]
            )
        families[family] = {
            "state": state,
            "reason": reason,
            "net_pnl_usd": source.get("net_pnl_usd") if isinstance(source, dict) else None,
            "evidence_paths": source.get("evidence_paths", []) if isinstance(source, dict) else [],
            "paper_only": True,
            "read_only": True,
            "real_execution": False,
        }

    current_coverage = health.get("coverage") if isinstance(health, dict) else {}
    if not isinstance(current_coverage, dict):
        current_coverage = {}
    expected_selection_id = (
        analysis_campaigns.get("selection_ids", [None])[0]
        if len(analysis_campaigns.get("selection_ids", [])) == 1
        else None
    )
    frozen_coverage_valid, frozen_coverage_reason, frozen_coverage_receipt = (
        validate_frozen_coverage_receipt(dataset, phase_map, expected_selection_id)
    )
    coverage = (
        frozen_coverage_receipt.get("coverage", {})
        if frozen_coverage_valid
        else {}
    )
    event_wiring_complete = bool(
        event_summary
        and not any(
            int(event_summary.get(key, 0))
            for key in ("MISSING", "BROKEN", "IMPLEMENTED_BUT_NOT_WIRED")
        )
    )
    exact_coverage_complete = all(
        coverage.get(key) is True
        for key in (
            "valid_record_count_exact",
            "unique_record_count_exact",
            "trade_count_exact",
            "unique_trade_count_exact",
            "uncompressed_bytes_exact",
        )
    )
    implementation_complete = bool(
        event_wiring_complete
        and exact_coverage_complete
        and frozen_coverage_valid
        and watchdog.get("watchdog_status") == "HEALTHY"
        and resilience.get("status") == "READY"
        and phase.get("phase") == "ANALYZE"
        and phase.get("analysis_stage") in {"SCOREBOARD", "DONE"}
        and analysis_complete
        and analysis_selection_coherent
        and resume_valid
        and scoreboard_valid
    )
    final_validation_complete = bool(
        implementation_complete
        and scoreboard.get("schema_version") == "hypersmart.economic_family_scoreboards.v2"
        and all(
            row["state"] in {"PROVEN", "MORE_DATA", "UNMEASURABLE", "KILL"}
            for row in families.values()
        )
        and all(
            not str(row["reason"]).startswith("CURRENT_SCOREBOARD_")
            for row in families.values()
        )
    )
    body = {
        "schema": "alina.global_implementation_closure.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alina_head": git_sha(alina),
        "dataset_v2_head": git_sha(dataset),
        "phase": phase,
        "event_intelligence": {
            "idea_count": len(event_status.get("items", [])) if isinstance(event_status, dict) else 0,
            "summary": event_summary or {},
            "wiring_complete": event_wiring_complete,
            "partial_proof_count": int((event_summary or {}).get("IMPLEMENTED_BUT_PARTIAL", 0)),
            "economic_proof_complete": event_wiring_complete
            and int((event_summary or {}).get("IMPLEMENTED_BUT_PARTIAL", 0)) == 0,
            "economic_proof_allowed": False,
        },
        "dataset": {
            "metrics_digest": metrics.get("metrics_digest"),
            "coverage": metrics.get("totals", {}),
            "watchdog_status": watchdog.get("watchdog_status"),
            "campaign_count": watchdog.get("campaign_count"),
        },
        "coverage_provenance": {
            "valid": frozen_coverage_valid,
            "reason": frozen_coverage_reason,
            "phase_epoch": frozen_coverage_receipt.get("phase_epoch") if isinstance(frozen_coverage_receipt, dict) else None,
            "source_collection_epoch": frozen_coverage_receipt.get("source_collection_epoch") if isinstance(frozen_coverage_receipt, dict) else None,
            "dataset_selection_id": frozen_coverage_receipt.get("dataset_selection_id") if isinstance(frozen_coverage_receipt, dict) else None,
            "index_sha256": frozen_coverage_receipt.get("index_sha256") if isinstance(frozen_coverage_receipt, dict) else None,
            "health_evidence_commit": frozen_coverage_receipt.get("health_evidence_commit") if isinstance(frozen_coverage_receipt, dict) else None,
            "health_receipt_digest": frozen_coverage_receipt.get("health_receipt_digest") if isinstance(frozen_coverage_receipt, dict) else None,
            "coverage": coverage,
            "current_global_coverage": current_coverage,
        },
        "scoreboard_provenance": {
            "valid": scoreboard_valid,
            "reason": scoreboard_reason,
            "campaign_id": scoreboard_receipt.get("campaign_id") if isinstance(scoreboard_receipt, dict) else None,
            "phase_epoch": scoreboard_receipt.get("phase_epoch") if isinstance(scoreboard_receipt, dict) else None,
            "source_collection_epoch": scoreboard_receipt.get("source_collection_epoch") if isinstance(scoreboard_receipt, dict) else None,
            "dataset_selection_id": scoreboard_receipt.get("dataset_selection_id") if isinstance(scoreboard_receipt, dict) else None,
            "scoreboard_sha256": scoreboard_receipt.get("scoreboard_sha256") if isinstance(scoreboard_receipt, dict) else None,
            "evidence_tag": scoreboard_receipt.get("evidence_tag") if isinstance(scoreboard_receipt, dict) else None,
            "environment_receipt_sha256": scoreboard_receipt.get("environment_receipt_sha256") if isinstance(scoreboard_receipt, dict) else None,
            "environment_provenance": scoreboard_receipt.get("environment_provenance") if isinstance(scoreboard_receipt, dict) else None,
        },
        "analysis_campaigns": analysis_campaigns,
        "economic_improvement": improvement_ledger if isinstance(improvement_ledger, dict) else {},
        "resume_provenance": {
            "valid": resume_valid,
            "reason": resume_reason,
            "campaign_id": resume_receipt.get("campaign_id") if isinstance(resume_receipt, dict) else None,
            "workflow_run_id": resume_receipt.get("workflow_run_id") if isinstance(resume_receipt, dict) else None,
            "segment_a_job_id": resume_receipt.get("segment_a_job_id") if isinstance(resume_receipt, dict) else None,
            "segment_b_job_id": resume_receipt.get("segment_b_job_id") if isinstance(resume_receipt, dict) else None,
            "terminal_selection_id": resume_receipt.get("terminal_selection_id") if isinstance(resume_receipt, dict) else None,
            "terminal_checkpoint_id": resume_receipt.get("terminal_checkpoint_id") if isinstance(resume_receipt, dict) else None,
            "terminal_evidence_digest": resume_receipt.get("terminal_evidence_digest") if isinstance(resume_receipt, dict) else None,
            "duplicate_completed_unit_count": resume_receipt.get("duplicate_completed_unit_count") if isinstance(resume_receipt, dict) else None,
            "duplicate_replay_work_count": resume_receipt.get("duplicate_replay_work_count") if isinstance(resume_receipt, dict) else None,
        },
        "families": families,
        "security": {
            "paper_only": True,
            "read_only": True,
            "real_execution": False,
            "carry": "DISABLED_BY_SCOPE",
            "execution_keys_present": False,
        },
        "cloud_only": True,
        "implementation_complete": implementation_complete,
        "final_validation_complete": final_validation_complete,
    }
    body["receipt_digest"] = digest(body)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "scoreboard_provenance_valid": scoreboard_valid,
                "receipt_digest": body["receipt_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
