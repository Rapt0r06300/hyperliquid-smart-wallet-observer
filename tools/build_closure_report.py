#!/usr/bin/env python3
"""Build a conservative dual-repository closure report from durable evidence."""
from __future__ import annotations
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path

def load(path: Path, default=None):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError): return default

def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dataset-root",required=True)
    p.add_argument("--output",default="docs/alina-closure-report.json")
    p.add_argument("--main-head",default=os.environ.get("ALINA_MAIN_HEAD","unknown"))
    p.add_argument("--dataset-head",default=os.environ.get("DATASET_V2_HEAD","unknown"))
    args=p.parse_args()
    root=Path(args.dataset_root)
    phase=load(root/"control/alina-phase.json",{})
    health=load(root/"catalog/DATASET_HEALTH_RECEIPT.json",{})
    event=load(Path("docs/event-intelligence-120-status.json"),{})
    spec=Path("docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md")
    spec_text=spec.read_text(encoding="utf-8") if spec.exists() else ""
    backlog=[]
    for line in spec_text.splitlines():
        match=re.match(r"^#{2,4}\s+((?:OPEN|WKR)-\d+)\s+[—-]\s*(.*)$",line)
        if match:
            backlog.append({"id":match.group(1),"title":match.group(2).strip(),"status":"BLOCKED","evidence":None})
    totals=health.get("totals") if isinstance(health,dict) else {}
    safety={"paper_only":True,"read_only":True,"real_execution":False,"self_hosted_required":False,"pc_dependency":False}
    modules={}
    for name in ("copy_vault","lead_lag","cross_venue_dislocation"):
        modules[name]={"status":"UNMEASURABLE","reason":"no independent final certificate loaded","certificate_digest":None}
    report={
        "schema_version":"alina.closure_report.v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "main_head":args.main_head,
        "dataset_v2_head":args.dataset_head,
        "phase":phase,
        "dataset_health_digest":health.get("receipt_digest") if isinstance(health,dict) else None,
        "dataset_totals":totals or {},
        "event_intelligence_registry_digest":event.get("registry_digest") if isinstance(event,dict) else None,
        "modules":modules,
        "safety":safety,
        "implementation_backlog":backlog,
        "closure_status":"BLOCKED" if backlog else "UNMEASURABLE",
        "unresolved_blockers":["final implementation backlog is not empty"] if backlog else ["economic certificates not loaded"],
    }
    report["report_digest"]=sha(report)
    Path(args.output).write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":args.output,"closure_status":report["closure_status"],"backlog_items":len(backlog),"report_digest":report["report_digest"]},sort_keys=True))
if __name__=="__main__":
    main()
