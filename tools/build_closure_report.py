#!/usr/bin/env python3
"""Build a conservative dual-repository closure receipt from durable evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _current_analysis_campaigns(campaigns, phase):
    """Return only campaigns bound to the canonical current ANALYZE epoch."""
    if not isinstance(phase, dict) or phase.get("phase") != "ANALYZE":
        return []
    epoch = phase.get("epoch")
    source_epoch = phase.get("source_collection_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int):
        return []
    return [
        row
        for row in campaigns
        if isinstance(row, dict)
        and row.get("creation_phase") == "ANALYZE"
        and row.get("phase_epoch") == epoch
        and row.get("source_collection_epoch") == source_epoch
    ]


def _validated_current_scoreboard(root, phase, current_campaigns):
    receipt = load(root / "catalog/ANALYSIS_SCOREBOARD_RECEIPT.json", {})
    if not isinstance(receipt, dict) or receipt.get("schema") != "alina.analysis_scoreboard_receipt.v1":
        return False, {}, receipt if isinstance(receipt, dict) else {}, "CURRENT_SCOREBOARD_RECEIPT_MISSING"

    stored_receipt_digest = str(receipt.get("receipt_digest") or "")
    receipt_body = dict(receipt)
    receipt_body.pop("receipt_digest", None)
    if len(stored_receipt_digest) != 64 or digest(receipt_body) != stored_receipt_digest:
        return False, {}, receipt, "CURRENT_SCOREBOARD_RECEIPT_DIGEST_INVALID"

    scoreboard = receipt.get("scoreboard")
    if not isinstance(scoreboard, dict):
        return False, {}, receipt, "CURRENT_SCOREBOARD_PAYLOAD_MISSING"
    if scoreboard.get("schema_version") != "hypersmart.economic_family_scoreboards.v2":
        return False, {}, receipt, "CURRENT_SCOREBOARD_SCHEMA_INVALID"
    if digest(scoreboard) != str(receipt.get("scoreboard_sha256") or ""):
        return False, {}, receipt, "CURRENT_SCOREBOARD_HASH_MISMATCH"
    if scoreboard.get("paper_read_only") is not True or scoreboard.get("real_execution") is not False:
        return False, {}, receipt, "CURRENT_SCOREBOARD_NOT_PAPER_ONLY"

    campaign_id = str(receipt.get("campaign_id") or "")
    campaign = next(
        (
            row for row in current_campaigns
            if str(row.get("campaign_id") or "") == campaign_id
            and row.get("kind") == "scoreboard"
        ),
        None,
    )
    if not isinstance(campaign, dict) or campaign.get("status") != "COMPLETE":
        return False, {}, receipt, "CURRENT_SCOREBOARD_CAMPAIGN_NOT_COMPLETE"

    bindings = (
        ("phase_epoch", phase.get("epoch")),
        ("source_collection_epoch", phase.get("source_collection_epoch")),
        ("dataset_selection_id", campaign.get("dataset_selection_id")),
        ("collection_cutoff_at_utc", campaign.get("collection_cutoff_at_utc")),
        ("code_sha", campaign.get("code_sha")),
    )
    for key, expected in bindings:
        if receipt.get(key) != expected:
            return False, {}, receipt, f"CURRENT_SCOREBOARD_BINDING_MISMATCH:{key}"

    env = receipt.get("environment_provenance")
    if not isinstance(env, dict) or not env:
        return False, {}, receipt, "CURRENT_SCOREBOARD_ENVIRONMENT_PROVENANCE_MISSING"
    if len(str(receipt.get("environment_receipt_sha256") or "")) != 64:
        return False, {}, receipt, "CURRENT_SCOREBOARD_ENVIRONMENT_HASH_MISSING"
    if not receipt.get("evidence_tag") or not receipt.get("evidence_repository"):
        return False, {}, receipt, "CURRENT_SCOREBOARD_DURABLE_EVIDENCE_MISSING"
    if receipt.get("paper_only") is not True or receipt.get("read_only") is not True or receipt.get("real_execution") is not False:
        return False, {}, receipt, "CURRENT_SCOREBOARD_RECEIPT_SAFETY_INVALID"
    return True, scoreboard, receipt, "CURRENT_SCOREBOARD_RECEIPT_VALID"


def _validated_global_closure(root, phase, expected_selection_id):
    receipt = load(root / "catalog/GLOBAL_IMPLEMENTATION_CLOSURE.json", {})
    if not isinstance(receipt, dict) or receipt.get("schema") != "alina.global_implementation_closure.v1":
        return False, receipt if isinstance(receipt, dict) else {}, "GLOBAL_CLOSURE_RECEIPT_MISSING"
    supplied = str(receipt.get("receipt_digest") or "")
    body = dict(receipt)
    body.pop("receipt_digest", None)
    if len(supplied) != 64 or digest(body) != supplied:
        return False, receipt, "GLOBAL_CLOSURE_RECEIPT_DIGEST_INVALID"
    if receipt.get("implementation_complete") is not True or receipt.get("final_validation_complete") is not True:
        return False, receipt, "GLOBAL_CLOSURE_NOT_COMPLETE"
    if receipt.get("cloud_only") is not True:
        return False, receipt, "GLOBAL_CLOSURE_NOT_CLOUD_ONLY"
    bound_phase = receipt.get("phase")
    for key in ("phase", "epoch", "source_collection_epoch", "analysis_stage", "collection_cutoff_at_utc"):
        if not isinstance(bound_phase, dict) or bound_phase.get(key) != phase.get(key):
            return False, receipt, f"GLOBAL_CLOSURE_PHASE_MISMATCH:{key}"
    provenance = receipt.get("coverage_provenance")
    if not isinstance(provenance, dict) or provenance.get("valid") is not True:
        return False, receipt, "GLOBAL_CLOSURE_FROZEN_COVERAGE_INVALID"
    if provenance.get("phase_epoch") != phase.get("epoch"):
        return False, receipt, "GLOBAL_CLOSURE_COVERAGE_EPOCH_STALE"
    if provenance.get("source_collection_epoch") != phase.get("source_collection_epoch"):
        return False, receipt, "GLOBAL_CLOSURE_COVERAGE_SOURCE_EPOCH_STALE"
    if provenance.get("dataset_selection_id") != expected_selection_id:
        return False, receipt, "GLOBAL_CLOSURE_COVERAGE_SELECTION_MISMATCH"
    coverage = provenance.get("coverage")
    exact_keys = (
        "valid_record_count_exact",
        "unique_record_count_exact",
        "trade_count_exact",
        "unique_trade_count_exact",
        "uncompressed_bytes_exact",
    )
    if not isinstance(coverage, dict) or not all(coverage.get(key) is True for key in exact_keys):
        return False, receipt, "GLOBAL_CLOSURE_FROZEN_COVERAGE_NOT_EXACT"
    return True, receipt, "GLOBAL_CLOSURE_RECEIPT_VALID"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", default="docs/alina-closure-report.json")
    parser.add_argument("--main-head", default=os.environ.get("ALINA_MAIN_HEAD", "unknown"))
    parser.add_argument("--dataset-head", default=os.environ.get("DATASET_V2_HEAD", "unknown"))
    parser.add_argument("--canonical-spec-blob", default=None)
    args = parser.parse_args()

    root = Path(args.dataset_root)
    phase = load(root / "control/alina-phase.json", {})
    operator_status_rows = []
    operator_status_invalid = []
    for status_path in sorted(Path("control/operator-status").glob("*.json")):
        row = load(status_path, None)
        if not isinstance(row, dict):
            operator_status_invalid.append(status_path.name)
            continue
        valid_states = {"DISPATCHED", "RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"}
        if (
            row.get("schema_version") != "alina.operator_status.v1"
            or not row.get("request_id")
            or row.get("state") not in valid_states
            or row.get("terminal") is not (row.get("state") in {"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})
        ):
            operator_status_invalid.append(status_path.name)
            continue
        operator_status_rows.append({
            "request_id": row.get("request_id"),
            "intent": row.get("intent"),
            "state": row.get("state"),
            "terminal": row.get("terminal") is True,
            "workflow_run_id": row.get("workflow_run_id"),
            "updated_at_utc": row.get("updated_at_utc"),
        })
    health = load(root / "catalog/DATASET_HEALTH_RECEIPT.json", {})
    global_closure = load(root / "catalog/GLOBAL_IMPLEMENTATION_CLOSURE.json", {})
    copy_vault_coverage = load(root / "catalog/COPY_VAULT_COVERAGE_RECEIPT.json", {})
    replay_patch = load(root / "catalog/REPLAY_COMPAT_PATCH.json", {})
    resilience = load(root / "catalog/CAMPAIGN_RESILIENCE_RECEIPT.json", {})
    resume_receipt = load(root / "catalog/RESUME_SMOKE_RECEIPT.json", {})
    event = load(Path("docs/event-intelligence-120-status.json"), {})
    source_matrix = load(Path("docs/source-capability-matrix.json"), {})
    gate_registry = load(Path("docs/normative-gate-registry.json"), {})
    spec = Path("docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md")
    spec_text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    declared_requirements = []
    for line in spec_text.splitlines():
        match = re.match(r"^#{2,4}\s+((?:OPEN|WKR)-\d+)\s+[—-]\s*(.*)$", line)
        if match:
            declared_requirements.append({
                "id": match.group(1),
                "title": match.group(2).strip(),
                "status": "DECLARED",
            })

    campaigns = []
    for path in sorted((root / "catalog/campaigns").glob("*.json")):
        row = load(path)
        if isinstance(row, dict):
            campaigns.append(row)
    totals = health.get("totals") if isinstance(health, dict) else {}
    items = event.get("items") if isinstance(event, dict) else []
    event_terminal_statuses = {"IMPLEMENTED_AND_WIRED", "NOT_APPLICABLE"}
    event_wired = (
        len(items) == 120
        and [row.get("id") for row in items] == list(range(1, 121))
        and all(row.get("status") in event_terminal_statuses for row in items)
    )
    replayable = int(totals.get("REPLAYABLE_SHARDS") or 0)
    replay_remaining = int((replay_patch or {}).get("remaining_candidates_for_filter") or 0)
    source_unvalidated = []
    source_degraded = []
    for venue in (source_matrix or {}).get("venues", []):
        venue_name = str(venue.get("venue") or venue.get("name") or "unknown")
        for capability, evidence in (venue.get("capabilities") or {}).items():
            runtime_status = str((evidence or {}).get("runtime_status") or "UNVALIDATED")
            row = {
                "venue": venue_name,
                "capability": str(capability),
                "runtime_status": runtime_status,
                "runtime_reason": (evidence or {}).get("runtime_reason"),
            }
            if runtime_status == "UNVALIDATED":
                source_unvalidated.append(row)
            elif runtime_status == "DEGRADED":
                source_degraded.append(row)
    resume_proven = (
        isinstance(resume_receipt, dict)
        and resume_receipt.get("segment_a_workflow_result") == "success"
        and resume_receipt.get("segment_b_workflow_result") == "success"
        and resume_receipt.get("terminal_campaign_status") == "COMPLETE"
        and int(resume_receipt.get("terminal_completed_units") or 0) > 0
    )
    campaign_ids = sorted(str(row.get("campaign_id")) for row in campaigns if row.get("campaign_id"))
    analysis_kinds = (
        "replay",
        "backtest",
        "oos",
        "forward_paper",
        "module_pnl_proof",
        "scoreboard",
    )
    current_analysis_campaigns = _current_analysis_campaigns(campaigns, phase)
    (
        current_scoreboard_valid,
        current_scoreboard,
        current_scoreboard_receipt,
        current_scoreboard_reason,
    ) = _validated_current_scoreboard(root, phase, current_analysis_campaigns)
    analysis_status = {
        str(row.get("kind")): str(row.get("status"))
        for row in current_analysis_campaigns
        if row.get("kind") in set(analysis_kinds)
    }
    complete_analysis = all(
        analysis_status.get(kind) == "COMPLETE"
        for kind in analysis_kinds
    )
    analyze_selections = sorted({
        str(row.get("dataset_selection_id"))
        for row in current_analysis_campaigns
        if row.get("dataset_selection_id")
    })
    expected_selection_id = analyze_selections[0] if len(analyze_selections) == 1 else None
    global_closure_valid, global_closure, global_closure_reason = (
        _validated_global_closure(root, phase, expected_selection_id)
    )
    frozen_coverage_provenance = (
        global_closure.get("coverage_provenance", {})
        if global_closure_valid
        else {}
    )
    frozen_coverage = (
        frozen_coverage_provenance.get("coverage", {})
        if isinstance(frozen_coverage_provenance, dict)
        else {}
    )
    trade_count_exact = frozen_coverage.get("trade_count_exact") is True
    unique_trade_count_exact = frozen_coverage.get("unique_trade_count_exact") is True
    uncompressed_size_exact = frozen_coverage.get("uncompressed_bytes_exact") is True
    uncompressed_size_coverage = uncompressed_size_exact

    workflow_run_ids = sorted({
        str((row.get("cursor") or {}).get("last_run_id"))
        for row in campaigns
        if isinstance(row.get("cursor"), dict)
        and (row.get("cursor") or {}).get("last_run_id")
    })
    scoreboard_artifact = (
        current_scoreboard_receipt.get("evidence_tag")
        if current_scoreboard_valid and isinstance(current_scoreboard_receipt, dict)
        else None
    )
    if not scoreboard_artifact:
        for row in current_analysis_campaigns:
            if row.get("kind") != "scoreboard":
                continue
            for unit in (row.get("completed_units") or {}).values():
                payload = unit.get("result") if isinstance(unit, dict) else None
                if isinstance(payload, dict):
                    scoreboard_artifact = (
                        payload.get("evidence_release_tag")
                        or payload.get("evidence_tag")
                        or payload.get("scoreboard_artifact")
                    )
                    if scoreboard_artifact:
                        break
    family_names = ("copy_vault", "lead_lag", "cross_venue_dislocation")
    scoreboard_families = (
        current_scoreboard.get("families")
        if current_scoreboard_valid
        and isinstance(current_scoreboard, dict)
        and isinstance(current_scoreboard.get("families"), dict)
        else {}
    )
    family_aliases = {
        "copy_vault": ("copy_vault",),
        "lead_lag": ("lead_lag",),
        "cross_venue_dislocation": ("cross_venue_dislocation", "cross_venue_dislocation_v2"),
    }
    valid_module_statuses = {"PROVEN", "MORE_DATA", "UNMEASURABLE", "KILL"}
    modules = {}
    for name in family_names:
        row = next(
            (
                scoreboard_families.get(alias)
                for alias in family_aliases[name]
                if isinstance(scoreboard_families.get(alias), dict)
            ),
            None,
        )
        if not isinstance(row, dict):
            modules[name] = {
                "status": "UNMEASURABLE",
                "reason": "no independent economic scoreboard evidence loaded",
                "certificate_digest": None,
            }
            continue
        verdict = str(row.get("verdict") or "UNMEASURABLE").upper()
        if verdict == "PASS":
            verdict = "PROVEN"
        if verdict not in valid_module_statuses:
            verdict = "UNMEASURABLE"
        reasons = row.get("verdict_reasons") or row.get("objective_reasons") or []
        modules[name] = {
            "status": verdict,
            "reason": "; ".join(str(value) for value in reasons[:8]) or "economic scoreboard evidence loaded",
            "certificate_digest": digest(row),
        }
    economic_evidence_loaded = current_scoreboard_valid and all(
        modules[name]["certificate_digest"] is not None for name in family_names
    )
    current_environment_provenance = (
        current_scoreboard_receipt.get("environment_provenance")
        if current_scoreboard_valid and isinstance(current_scoreboard_receipt, dict)
        else None
    )
    report = {
        "schema_version": "alina.final_closure_receipt.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "main_alina_head": args.main_head,
        "dataset_v2_head": args.dataset_head,
        "canonical_spec_blob": args.canonical_spec_blob,
        "phase": phase.get("phase"),
        "phase_epoch": phase.get("epoch"),
        "source_collection_epoch": phase.get("source_collection_epoch"),
        "analysis_stage": phase.get("analysis_stage"),
        "campaign_ids": campaign_ids,
        "workflow_run_ids": workflow_run_ids,
        "operator_status": {
            "count": len(operator_status_rows),
            "rows": operator_status_rows,
            "invalid_files": sorted(operator_status_invalid),
            "non_terminal_count": sum(1 for row in operator_status_rows if not row["terminal"]),
        },
        "dataset_selection_id": (
            analyze_selections[0] if len(analyze_selections) == 1 else None
        ),
        "trade_count_exact": trade_count_exact,
        "unique_trade_count_exact": unique_trade_count_exact,
        "safe_count": int(totals.get("SAFE_SHARDS") or 0),
        "partial_count": int(totals.get("PARTIAL_SHARDS") or 0),
        "rejected_count": int(totals.get("REJECTED_SHARDS") or 0),
        "quarantined_record_count": int(totals.get("TOTAL_QUARANTINED_RECORDS") or 0),
        "replay_compatible_count": replayable,
        "raw_record_count": int(totals.get("TOTAL_RECORDS") or 0),
        "valid_record_count": int(totals.get("TOTAL_VALID_RECORDS") or 0),
        "unique_record_count": int(totals.get("TOTAL_UNIQUE_RECORDS") or 0),
        "raw_trade_count": int(totals.get("TOTAL_TRADES_COLLECTED") or 0),
        "unique_trade_count_global": totals.get("TOTAL_UNIQUE_TRADES_GLOBAL"),
        "trade_count_failure_reason_count": int(totals.get("TRADE_COUNT_FAILURE_REASON_COUNT") or 0),
        "global_unique_failure_reason_count": int(totals.get("GLOBAL_UNIQUE_FAILURE_REASON_COUNT") or 0),
        "cross_shard_overlap_trade_count": int(totals.get("TOTAL_CROSS_SHARD_OVERLAP_TRADES") or 0),
        "uncompressed_size_coverage": uncompressed_size_coverage,
        "uncompressed_size_exact": uncompressed_size_exact,
        "uncompressed_size_exact_assets": (health.get("coverage") or {}).get("uncompressed_size_exact_assets", 0) if isinstance(health, dict) else 0,
        "uncompressed_size_unavailable_assets": (health.get("coverage") or {}).get("uncompressed_size_unavailable_assets", 0) if isinstance(health, dict) else 0,
        "copy_vault_status": modules["copy_vault"]["status"],
        "lead_lag_status": modules["lead_lag"]["status"],
        "cross_venue_status": modules["cross_venue_dislocation"]["status"],
        "oos_status": "MORE_DATA" if not complete_analysis else "UNMEASURABLE",
        "forward_status": "MORE_DATA" if not complete_analysis else "UNMEASURABLE",
        "two_segment_resume_status": "PROVEN" if resume_proven else "UNMEASURABLE",
        "replay_remaining_candidates": replay_remaining,
        "campaign_resilience_status": (
            resilience.get("status") if isinstance(resilience, dict) else "UNAVAILABLE"
        ),
        "source_unvalidated_capability_count": len(source_unvalidated),
        "source_unvalidated_capabilities": source_unvalidated,
        "source_degraded_capability_count": len(source_degraded),
        "source_degraded_capabilities": source_degraded,
        "event_intelligence_wiring_complete": event_wired,
        "scoreboard_artifact": scoreboard_artifact,
        "global_closure_provenance": {
            "valid": global_closure_valid,
            "reason": global_closure_reason,
            "receipt_digest": global_closure.get("receipt_digest") if isinstance(global_closure, dict) else None,
            "dataset_v2_head": global_closure.get("dataset_v2_head") if isinstance(global_closure, dict) else None,
            "coverage": frozen_coverage_provenance,
        },
        "scoreboard_provenance": {
            "valid": current_scoreboard_valid,
            "reason": current_scoreboard_reason,
            "campaign_id": current_scoreboard_receipt.get("campaign_id") if isinstance(current_scoreboard_receipt, dict) else None,
            "phase_epoch": current_scoreboard_receipt.get("phase_epoch") if isinstance(current_scoreboard_receipt, dict) else None,
            "source_collection_epoch": current_scoreboard_receipt.get("source_collection_epoch") if isinstance(current_scoreboard_receipt, dict) else None,
            "dataset_selection_id": current_scoreboard_receipt.get("dataset_selection_id") if isinstance(current_scoreboard_receipt, dict) else None,
            "scoreboard_sha256": current_scoreboard_receipt.get("scoreboard_sha256") if isinstance(current_scoreboard_receipt, dict) else None,
            "environment_receipt_sha256": current_scoreboard_receipt.get("environment_receipt_sha256") if isinstance(current_scoreboard_receipt, dict) else None,
            "evidence_tag": current_scoreboard_receipt.get("evidence_tag") if isinstance(current_scoreboard_receipt, dict) else None,
        },
        "copy_vault_coverage_receipt": {
            "status": copy_vault_coverage.get("status") if isinstance(copy_vault_coverage, dict) else "UNAVAILABLE",
            "digest": copy_vault_coverage.get("receipt_digest") if isinstance(copy_vault_coverage, dict) else None,
            "reconciliation": copy_vault_coverage.get("reconciliation") if isinstance(copy_vault_coverage, dict) else {},
        },
        "paper_read_only": True,
        "self_hosted_used": False,
        "real_execution_reachable": False,
        "remaining_blockers": [
            f"current-epoch economic scoreboard evidence is invalid: {current_scoreboard_reason}" if not economic_evidence_loaded else None,
            f"dataset global closure evidence is invalid: {global_closure_reason}" if not global_closure_valid else None,
            "exact trade count coverage is incomplete" if not trade_count_exact else None,
            "global unique trade count coverage is incomplete" if not unique_trade_count_exact else None,
            f"SAFE to replay-compatible migration has {replay_remaining} unclassified candidates" if replay_remaining > 0 else None,
            "campaign resilience receipt is not READY" if not isinstance(resilience, dict) or resilience.get("status") != "READY" else None,
            "fresh-runner two-segment resume proof is unavailable" if not resume_proven else None,
            f"source capability matrix has {len(source_unvalidated)} unvalidated capabilities" if source_unvalidated else None,
            "event intelligence contains non-wired or partial rows" if not event_wired else None,
            "analysis campaigns are not all terminal COMPLETE" if not complete_analysis else None,
            "uncompressed size coverage is incomplete" if not uncompressed_size_coverage else None,
            "normative gate registry is unavailable" if not gate_registry else None,
            "operator status receipt is invalid" if operator_status_invalid else None,
            "current-epoch environment provenance is unavailable" if complete_analysis and not current_environment_provenance else None,
        ],
        "declared_spec_requirements": declared_requirements,
        "implementation_backlog": [],
        "analysis_campaign_status": analysis_status,
        "modules": modules,
        "dataset_health_digest": health.get("receipt_digest") if isinstance(health, dict) else None,
        "event_intelligence_registry_digest": event.get("registry_digest") if isinstance(event, dict) else None,
        "normative_gate_registry_digest": gate_registry.get("registry_digest") if isinstance(gate_registry, dict) else None,
        "normative_gate_count": gate_registry.get("gate_count", 0) if isinstance(gate_registry, dict) else 0,
        "environment_provenance": current_environment_provenance,
    }
    report["remaining_blockers"] = [
        value for value in report["remaining_blockers"] if value
    ]
    report["implementation_backlog"] = [
        {
            "id": f"BLOCKER-{index:02d}",
            "status": "UNRESOLVED",
            "reason": reason,
        }
        for index, reason in enumerate(report["remaining_blockers"], start=1)
    ]

    # Canonical execution ledger required by the specification.  This is not a
    # second source of truth: every state is derived from the same durable
    # evidence already used by this receipt.
    implementation_surface_done = all(
        (
            bool(gate_registry),
            event_wired,
            not source_unvalidated,
            replay_remaining == 0,
            trade_count_exact,
            uncompressed_size_coverage,
            global_closure_valid,
            isinstance(resilience, dict) and resilience.get("status") == "READY",
        )
    )
    report["execution_ledger"] = [
        {
            "id": "canonical-implementation-surface",
            "state": "DONE" if implementation_surface_done else "BLOCKED",
            "reason": (
                "canonical control/data/gate surface is wired"
                if implementation_surface_done
                else "one or more implementation-surface gates remain unresolved"
            ),
        },
        {
            "id": "global-unique-trade-identity",
            "state": (
                "DONE"
                if unique_trade_count_exact
                else "IN_PROGRESS"
            ),
            "reason": (
                "global unique trade identity coverage is exact"
                if unique_trade_count_exact
                else "global unique trade identity backfill/reconciliation remains incomplete"
            ),
        },
        {
            "id": "analysis-chain",
            "state": "DONE" if complete_analysis else "BLOCKED",
            "reason": (
                "current-epoch replay/backtest/OOS/forward/PnL/scoreboard campaigns are terminal"
                if complete_analysis
                else "current-epoch analysis stages cannot be declared complete yet"
            ),
        },
        {
            "id": "two-segment-resume-proof",
            "state": "DONE" if resume_proven else "BLOCKED",
            "reason": (
                "fresh-runner two-segment resume proof is durable"
                if resume_proven
                else "fresh-runner two-segment resume proof is not durable yet"
            ),
        },
        {
            "id": "final-dual-repository-closure",
            "state": "DONE" if not report["remaining_blockers"] else "TODO",
            "reason": (
                "no canonical closure blocker remains"
                if not report["remaining_blockers"]
                else f"{len(report['remaining_blockers'])} canonical closure blocker(s) remain"
            ),
        },
    ]
    report["receipt_digest"] = digest(report)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": args.output,
        "closure_status": "BLOCKED" if report["remaining_blockers"] else "UNMEASURABLE",
        "backlog_items": len(report["implementation_backlog"]),
        "declared_requirements": len(declared_requirements),
        "receipt_digest": report["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
