#!/usr/bin/env python3
"""Build a deterministic explanation for SAFE/replayable population differences."""
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
INDEX=ROOT/"catalog"/"DATA_INDEX.json"
OUTPUT=ROOT/"catalog"/"REPLAY_COMPATIBILITY_REASONS.json"

def canonical(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--output",default=str(OUTPUT))
    args=p.parse_args()
    index=json.loads(INDEX.read_text(encoding="utf-8"))
    rows=index.get("shards") or []
    reasons=Counter()
    classifications=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        status=str(row.get("quality_status") or "UNKNOWN")
        replay=row.get("replay_compatible") is True
        if status=="SAFE" and replay:
            reason="SAFE_REPLAY_COMPATIBLE"
        elif status=="SAFE" and not replay:
            reason=str(row.get("replay_reason") or "REPLAY_COMPATIBILITY_NOT_PROVEN")
        elif status!="SAFE" and replay:
            reason=f"REPLAYABLE_BUT_{status}"
        else:
            reason=f"NOT_SAFE_OR_REPLAYABLE:{status}:{row.get('replay_reason') or 'NO_REPLAY_COMPATIBILITY'}"
        reasons[reason]+=1
        classifications.append({
            "dataset_id":row.get("dataset_id"),
            "family":row.get("family"),
            "quality_status":status,
            "replay_compatible":replay,
            "reason_code":reason,
            "replay_schema_version":row.get("replay_schema_version"),
        })
    body={
        "schema":"alina.replay_compatibility_reasons.v1",
        "source_index_sha256":hashlib.sha256(INDEX.read_bytes()).hexdigest(),
        "row_count":len(classifications),
        "reason_counts":dict(sorted(reasons.items())),
        "classifications":sorted(classifications,key=lambda x:str(x.get("dataset_id") or "")),
        "safe_not_replayable_count":sum(1 for x in classifications if x["quality_status"]=="SAFE" and not x["replay_compatible"]),
        "replayable_not_safe_count":sum(1 for x in classifications if x["quality_status"]!="SAFE" and x["replay_compatible"]),
    }
    body["receipt_digest"]=hashlib.sha256(canonical(body).encode()).hexdigest()
    Path(args.output).write_text(json.dumps(body,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"row_count":body["row_count"],"safe_not_replayable_count":body["safe_not_replayable_count"],"replayable_not_safe_count":body["replayable_not_safe_count"],"receipt_digest":body["receipt_digest"]},sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
