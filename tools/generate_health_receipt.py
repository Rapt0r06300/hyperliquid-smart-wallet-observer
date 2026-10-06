#!/usr/bin/env python3
"""Generate the lightweight, machine-readable Dataset V2 health receipt."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

def canonical(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

ANALYSIS_STAGE_BY_KIND = {
    "replay": "REPLAY",
    "backtest": "BACKTEST",
    "oos": "OOS",
    "forward_paper": "FORWARD_PAPER",
    "module_pnl_proof": "PNL_PROOF",
    "scoreboard": "SCOREBOARD",
}

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--metrics",default="catalog/DATA_METRICS.json")
    p.add_argument("--phase",default="control/alina-phase.json")
    p.add_argument("--campaign-dir",default="catalog/campaigns")
    p.add_argument("--output",default="catalog/DATASET_HEALTH_RECEIPT.json")
    p.add_argument("--replay-reasons",default="catalog/REPLAY_COMPATIBILITY_REASONS.json")
    p.add_argument("--dataset-commit",required=True)
    args=p.parse_args()
    metrics=load(Path(args.metrics))
    phase=load(Path(args.phase))
    replay_reasons=load(Path(args.replay_reasons)) if Path(args.replay_reasons).is_file() else {}
    totals=dict(metrics.get("totals") or {})
    campaigns=[]
    for path in sorted(Path(args.campaign_dir).glob("*.json")):
        try:
            row=load(path)
        except (OSError,ValueError):
            continue
        campaigns.append({
            "campaign_id":row.get("campaign_id"),
            "kind":row.get("kind"),
            "analysis_stage": row.get("analysis_stage") or ANALYSIS_STAGE_BY_KIND.get(str(row.get("kind") or "")),
            "status":row.get("status"),
            "status_reason":row.get("status_reason"),
            "phase_epoch":row.get("phase_epoch"),
            "source_collection_epoch":row.get("source_collection_epoch"),
            "collection_cutoff_at_utc":row.get("collection_cutoff_at_utc"),
            "creation_phase":row.get("creation_phase"),
            "chunk_index":row.get("chunk_index"),
            "attempts":row.get("attempts"),
            "no_progress_count":row.get("no_progress_count"),
            "consecutive_failures":row.get("consecutive_failures"),
            "lease":row.get("lease"),
            "updated_at":row.get("updated_at"),
            "next_due_at":row.get("next_due_at"),
            "last_checkpoint_id":(row.get("cursor") or {}).get("checkpoint_id") if isinstance(row.get("cursor"),dict) else None,
            "completed_unit_count":len(row.get("completed_units") or {}) if isinstance(row.get("completed_units"),dict) else 0,
            "lease_owner":(row.get("lease") or {}).get("owner_run_id") if isinstance(row.get("lease"),dict) else None,
            "lease_expires_at":(row.get("lease") or {}).get("expires_at") if isinstance(row.get("lease"),dict) else None,
        })
    phase_mismatches=[]
    active_statuses={"PENDING","RUNNING","CONTINUATION_REQUIRED","STUCK"}
    for row in campaigns:
        if row["status"] not in active_statuses:
            continue
        campaign_epoch = int(row.get("phase_epoch") or 0)
        phase_epoch = int(phase.get("epoch") or 0)
        pinned_collect_continuation = (
            phase.get("phase") == "COLLECT"
            and row.get("creation_phase") == "COLLECT"
            and 0 < campaign_epoch <= phase_epoch
        )
        if campaign_epoch != phase_epoch and not pinned_collect_continuation:
            phase_mismatches.append({
                "campaign_id": row.get("campaign_id"),
                "reason": "PHASE_EPOCH_MISMATCH",
            })
            continue
        if phase.get("phase") == "COLLECT" and row.get("creation_phase") != "COLLECT":
            phase_mismatches.append({
                "campaign_id": row.get("campaign_id"),
                "reason": "COLLECT_KIND_PHASE_MISMATCH",
            })
        if phase.get("phase") == "ANALYZE" and (
            row.get("creation_phase") != "ANALYZE"
            or row.get("source_collection_epoch") != phase.get("source_collection_epoch")
            or row.get("collection_cutoff_at_utc") != phase.get("collection_cutoff_at_utc")
            or (
                row.get("analysis_stage") is not None
                and row.get("analysis_stage") != phase.get("analysis_stage")
            )
        ):
            phase_mismatches.append({
                "campaign_id": row.get("campaign_id"),
                "reason": "ANALYZE_FREEZE_MISMATCH",
            })
    counts={}
    backlog_by_kind={}
    stuck=[]
    pending=[]
    for row in campaigns:
        key=f'{row["kind"]}:{row["status"]}'
        counts[key]=counts.get(key,0)+1
        if row["status"] in {"PENDING","CONTINUATION_REQUIRED","STUCK"}:
            backlog_by_kind[row["kind"]]=backlog_by_kind.get(row["kind"],0)+1
        if row["status"]=="STUCK":
            stuck.append({"campaign_id":row["campaign_id"],"kind":row["kind"],"reason":row["status_reason"],"next_due_at":row.get("next_due_at")})
        if row["status"]=="PENDING":
            pending.append(row)
    pending_ages=[row.get("updated_at") for row in campaigns if row.get("status")=="PENDING" and row.get("updated_at")]
    due_ages=[row.get("next_due_at") for row in campaigns if row.get("next_due_at")]
    body={
        "schema_version":"alina.dataset_health_receipt.v2",
        "dataset_commit":args.dataset_commit,
        "metrics_schema_version":metrics.get("schema_version"),
        "metrics_method":metrics.get("method"),
        "phase":phase,
        "totals":totals,
        "by_venue":metrics.get("by_venue") or {},
        "by_family":metrics.get("by_family") or {},
        "by_symbol":metrics.get("by_symbol") or {},
        "metrics_digest":hashlib.sha256(canonical(metrics).encode()).hexdigest(),
        "replay_compatibility_reasons": {
            "receipt_digest": replay_reasons.get("receipt_digest") if isinstance(replay_reasons,dict) else None,
            "reason_counts": replay_reasons.get("reason_counts") if isinstance(replay_reasons,dict) else {},
            "safe_not_replayable_count": replay_reasons.get("safe_not_replayable_count") if isinstance(replay_reasons,dict) else None,
            "replayable_not_safe_count": replay_reasons.get("replayable_not_safe_count") if isinstance(replay_reasons,dict) else None,
        },
        "campaign_counts":counts,
        "backlog_by_kind":backlog_by_kind,
        "stuck_campaigns":stuck,
        "pending_campaign_count":len(pending),
        "oldest_pending_updated_at":min(pending_ages) if pending_ages else None,
        "oldest_next_due_at":min(due_ages) if due_ages else None,
        "campaigns":campaigns,
        "phase_consistency":{
            "status":"BLOCKED" if phase_mismatches else "CONSISTENT",
            "mismatches":phase_mismatches,
        },
        "coverage":{
            "valid_record_count_exact":bool(totals.get("VALID_RECORDS_COVERAGE_COMPLETE")),
            "unique_record_count_exact":bool(totals.get("UNIQUE_RECORDS_COVERAGE_COMPLETE")),
            "trade_count_exact":bool(totals.get("TOTAL_TRADES_COUNT_COVERAGE_COMPLETE")),
            "trade_count_failure_reason_count":int(totals.get("TRADE_COUNT_FAILURE_REASON_COUNT") or 0),
            "unique_trade_count_exact":bool(totals.get("TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE")),
            "cross_shard_overlap_trades":int(totals.get("TOTAL_CROSS_SHARD_OVERLAP_TRADES") or 0),
            "uncompressed_bytes_coverage_complete":totals.get("UNCOMPRESSED_SIZE_COVERAGE_COMPLETE") is True,
            "uncompressed_bytes_exact":(
                totals.get("UNCOMPRESSED_SIZE_COVERAGE_COMPLETE") is True
                and int(totals.get("UNCOMPRESSED_SIZE_UNCLASSIFIED_ASSETS") or 0) == 0
                and int(totals.get("UNCOMPRESSED_SIZE_EXACT_ASSETS") or 0) > 0
            ),
            "uncompressed_size_exact_assets":int(totals.get("UNCOMPRESSED_SIZE_EXACT_ASSETS") or 0),
            "uncompressed_size_unavailable_assets":int(totals.get("UNCOMPRESSED_SIZE_UNAVAILABLE_ASSETS") or 0),
            "uncompressed_size_unclassified_assets":int(totals.get("UNCOMPRESSED_SIZE_UNCLASSIFIED_ASSETS") or 0),
            "safe_shards":int(totals.get("SAFE_SHARDS") or 0),
            "replayable_shards":int(totals.get("REPLAYABLE_SHARDS") or 0),
        },
    }
    body["receipt_digest"]=hashlib.sha256(canonical(body).encode()).hexdigest()
    Path(args.output).write_text(json.dumps(body,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":args.output,"receipt_digest":body["receipt_digest"],"campaigns":len(campaigns)},sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
