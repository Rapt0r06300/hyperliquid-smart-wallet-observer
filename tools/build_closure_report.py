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
    health = load(root / "catalog/DATASET_HEALTH_RECEIPT.json", {})
    event = load(Path("docs/event-intelligence-120-status.json"), {})
    spec = Path("docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md")
    spec_text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    backlog = []
    for line in spec_text.splitlines():
        match = re.match(r"^#{2,4}\s+((?:OPEN|WKR)-\d+)\s+[—-]\s*(.*)$", line)
        if match:
            backlog.append({
                "id": match.group(1),
                "title": match.group(2).strip(),
                "status": "UNRESOLVED",
                "evidence": None,
            })

    campaigns = []
    for path in sorted((root / "catalog/campaigns").glob("*.json")):
        row = load(path)
        if isinstance(row, dict):
            campaigns.append(row)
    totals = health.get("totals") if isinstance(health, dict) else {}
    items = event.get("items") if isinstance(event, dict) else []
    event_wired = bool(items) and all(
        row.get("status") == "IMPLEMENTED_AND_WIRED" for row in items
    )
    replayable = int(totals.get("REPLAYABLE_SHARDS") or 0)
    campaign_ids = sorted(str(row.get("campaign_id")) for row in campaigns if row.get("campaign_id"))
    analysis_kinds = (
        "replay",
        "backtest",
        "oos",
        "forward_paper",
        "module_pnl_proof",
        "scoreboard",
    )
    analysis_status = {
        str(row.get("kind")): str(row.get("status"))
        for row in campaigns
        if row.get("kind") in set(analysis_kinds)
    }
    complete_analysis = all(
        analysis_status.get(kind) == "COMPLETE"
        for kind in analysis_kinds
    )
    analyze_selections = sorted({
        str(row.get("dataset_selection_id"))
        for row in campaigns
        if row.get("creation_phase") == "ANALYZE"
        and row.get("dataset_selection_id")
    })
    workflow_run_ids = sorted({
        str((row.get("cursor") or {}).get("last_run_id"))
        for row in campaigns
        if isinstance(row.get("cursor"), dict)
        and (row.get("cursor") or {}).get("last_run_id")
    })
    scoreboard_artifact = None
    for row in campaigns:
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
    modules = {
        name: {
            "status": "UNMEASURABLE",
            "reason": "no independent final certificate loaded",
            "certificate_digest": None,
        }
        for name in family_names
    }
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
        "dataset_selection_id": (
            analyze_selections[0] if len(analyze_selections) == 1 else None
        ),
        "trade_count_exact": bool(totals.get("TOTAL_TRADES_COUNT_COVERAGE_COMPLETE")),
        "unique_trade_count_exact": bool(totals.get("TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE")),
        "safe_count": int(totals.get("SAFE_SHARDS") or 0),
        "replay_compatible_count": replayable,
        "copy_vault_status": modules["copy_vault"]["status"],
        "lead_lag_status": modules["lead_lag"]["status"],
        "cross_venue_status": modules["cross_venue_dislocation"]["status"],
        "oos_status": "MORE_DATA" if not complete_analysis else "UNMEASURABLE",
        "forward_status": "MORE_DATA" if not complete_analysis else "UNMEASURABLE",
        "two_segment_resume_status": (
            "PROVEN"
            if (
                isinstance(load(root / "catalog/RESUME_SMOKE_RECEIPT.json"), dict)
                and load(root / "catalog/RESUME_SMOKE_RECEIPT.json").get(
                    "segment_a_workflow_result"
                ) == "success"
                and load(root / "catalog/RESUME_SMOKE_RECEIPT.json").get(
                    "segment_b_workflow_result"
                ) == "success"
            )
            else "UNMEASURABLE"
        ),
        "event_intelligence_wiring_complete": event_wired,
        "scoreboard_artifact": scoreboard_artifact,
        "paper_read_only": True,
        "self_hosted_used": False,
        "real_execution_reachable": False,
        "remaining_blockers": [
            "implementation backlog is not empty" if backlog else "economic certificates not loaded",
            "event intelligence contains non-wired or partial rows" if not event_wired else None,
            "analysis campaigns are not all terminal COMPLETE" if not complete_analysis else None,
        ],
        "implementation_backlog": backlog,
        "analysis_campaign_status": analysis_status,
        "modules": modules,
        "dataset_health_digest": health.get("receipt_digest") if isinstance(health, dict) else None,
        "event_intelligence_registry_digest": event.get("registry_digest") if isinstance(event, dict) else None,
    }
    report["remaining_blockers"] = [
        value for value in report["remaining_blockers"] if value
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
        "backlog_items": len(backlog),
        "receipt_digest": report["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
