#!/usr/bin/env python3
"""Fail-closed phase/epoch gate for Dataset V2 campaign creation and workers."""
from __future__ import annotations
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

PHASES={"IDLE","COLLECT","ANALYZE"}
ANALYSIS_STAGES={"DRAIN","QUALITY","REPLAY","BACKTEST","OOS","FORWARD_PAPER","PNL_PROOF","SCOREBOARD","DONE"}
COLLECT_KINDS={"market_collection","copy_vault_collection","official_archive_collection","event_intelligence_collection"}
ANALYZE_KINDS={"replay","backtest","oos","forward_paper","module_pnl_proof","scoreboard"}
ANALYSIS_STAGE_BY_KIND={
    "replay":"REPLAY",
    "backtest":"BACKTEST",
    "oos":"OOS",
    "forward_paper":"FORWARD_PAPER",
    "module_pnl_proof":"PNL_PROOF",
    "scoreboard":"SCOREBOARD",
}

def load(path: Path) -> dict:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"invalid phase state: {exc}")
    if not isinstance(value,dict):
        raise SystemExit("invalid phase state: expected object")
    required={"schema_version","phase","epoch","requested_at_utc","collection_started_at_utc",
              "collection_cutoff_at_utc","source_collection_epoch","analysis_stage"}
    missing=required-set(value)
    if missing:
        raise SystemExit(f"invalid phase state: missing {sorted(missing)}")
    if value["schema_version"] != 1 or value["phase"] not in PHASES:
        raise SystemExit("invalid phase schema or phase")
    if not isinstance(value["epoch"],int) or value["epoch"] < 1:
        raise SystemExit("invalid phase epoch")
    for key in ("requested_at_utc","collection_started_at_utc","collection_cutoff_at_utc"):
        if value[key] is not None:
            try:
                parsed = datetime.fromisoformat(str(value[key]).replace("Z","+00:00"))
            except ValueError:
                raise SystemExit(f"invalid timestamp: {key}")
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise SystemExit(f"timestamp must be timezone-aware: {key}")
    phase=value["phase"]
    if phase=="IDLE" and any(value[k] is not None for k in ("collection_started_at_utc","collection_cutoff_at_utc","source_collection_epoch","analysis_stage")):
        raise SystemExit("IDLE state contains active-phase fields")
    if phase=="COLLECT" and (value["collection_started_at_utc"] is None or value["collection_cutoff_at_utc"] is not None or value["source_collection_epoch"] is not None or value["analysis_stage"] is not None):
        raise SystemExit("invalid COLLECT state")
    if phase=="ANALYZE" and (
        value["collection_cutoff_at_utc"] is None
        or isinstance(value["source_collection_epoch"], bool)
        or not isinstance(value["source_collection_epoch"], int)
        or value["source_collection_epoch"] < 1
        or value["analysis_stage"] not in ANALYSIS_STAGES
    ):
        raise SystemExit("invalid ANALYZE state")
    if phase=="ANALYZE":
        started=datetime.fromisoformat(str(value["collection_started_at_utc"]).replace("Z","+00:00"))
        cutoff=datetime.fromisoformat(str(value["collection_cutoff_at_utc"]).replace("Z","+00:00"))
        if cutoff < started:
            raise SystemExit("ANALYZE cutoff precedes collection start")
    return value

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=["read","allow","manifest"])
    p.add_argument("--state",default="control/alina-phase.json")
    p.add_argument("--kind")
    p.add_argument("--manifest")
    args=p.parse_args()
    state=load(Path(args.state))
    if args.command=="read":
        print(json.dumps(state,sort_keys=True))
        return 0
    if args.command=="allow":
        if not args.kind: raise SystemExit("--kind required")
        allowed = (
            state["phase"] == "COLLECT" and args.kind in COLLECT_KINDS
        ) or (
            state["phase"] == "ANALYZE"
            and args.kind in ANALYZE_KINDS
            and state.get("analysis_stage") == ANALYSIS_STAGE_BY_KIND.get(args.kind)
        )
        if not allowed: return 1
        print(json.dumps({
            "phase": state["phase"],
            "phase_epoch": state["epoch"],
            "analysis_stage": state.get("analysis_stage"),
            "source_collection_epoch": state["source_collection_epoch"],
            "collection_cutoff_at_utc": state["collection_cutoff_at_utc"],
        }, sort_keys=True))
        return 0
    if not args.manifest: raise SystemExit("--manifest required")
    try: manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc: raise SystemExit(f"invalid manifest: {exc}")
    if manifest.get("schema_version")!="alina.resumable_campaign.v2":
        raise SystemExit("phase-aware worker refuses v1 manifest")
    campaign_id = str(manifest.get("campaign_id") or "").strip()
    if not campaign_id:
        raise SystemExit("manifest campaign_id required")
    operator_request_id = manifest.get("operator_request_id")
    if campaign_id.startswith("operator-"):
        if not isinstance(operator_request_id, str) or not re.fullmatch(r"[0-9a-f]{64}", operator_request_id):
            raise SystemExit("operator campaign requires canonical request identity")
    creation_phase = str(manifest.get("creation_phase") or "")
    if creation_phase not in PHASES:
        raise SystemExit("manifest creation_phase invalid")
    manifest_epoch = manifest.get("phase_epoch")
    if (
        isinstance(manifest_epoch, bool)
        or not isinstance(manifest_epoch, int)
        or manifest_epoch < 1
        or creation_phase != state["phase"]
        or manifest_epoch != state["epoch"]
    ):
        raise SystemExit("manifest phase/epoch mismatch")
    kind = str(manifest.get("kind") or "")
    allowed_kinds = COLLECT_KINDS if state["phase"] == "COLLECT" else ANALYZE_KINDS
    if kind not in allowed_kinds:
        raise SystemExit(f"manifest kind {kind!r} is not allowed in phase {state['phase']}")
    if (
        state["phase"] == "ANALYZE"
        and state.get("analysis_stage") != ANALYSIS_STAGE_BY_KIND.get(kind)
    ):
        raise SystemExit(
            f"manifest kind {kind!r} is not allowed in analysis stage "
            f"{state.get('analysis_stage')!r}"
        )
    if state["phase"]=="ANALYZE":
        if manifest.get("source_collection_epoch")!=state["source_collection_epoch"] or manifest.get("collection_cutoff_at_utc")!=state["collection_cutoff_at_utc"]:
            raise SystemExit("manifest analysis freeze mismatch")
    print(json.dumps({"phase":state["phase"],"epoch":state["epoch"],"campaign_id":campaign_id},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
