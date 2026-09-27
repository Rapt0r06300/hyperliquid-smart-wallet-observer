#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",default="docs/event-intelligence-120-coverage.md")
    p.add_argument("--output",default="docs/event-intelligence-120-status.json")
    p.add_argument("--repo-root",default=".")
    a=p.parse_args()
    root=Path(a.repo_root)
    rows=[]
    for line in Path(a.source).read_text(encoding="utf-8").splitlines():
        m=ROW.match(line)
        if not m: continue
        number=int(m.group(1)); idea=m.group(2).strip(); refs=m.group(3).strip(); proof=m.group(5).strip()
        files=[]
        for token in re.split(r"\s*[+,/]\s*|\s+\+\s+",refs):
            token=token.strip()
            if token.endswith(".py"):
                files.extend(str(x.relative_to(root)) for x in list(root.rglob(token.split(":")[0]))[:5])
        files=sorted(set(files))
        status="MISSING" if not files else ("IMPLEMENTED_BUT_PARTIAL" if ("À prouver" in proof or "⏳" in proof) else "IMPLEMENTED_AND_WIRED")
        rows.append({"id":number,"idea":idea,"declared_references":refs,"evidence_files":files,"status":status,"proof_status":"UNMEASURABLE" if "⏳" in proof or "À prouver" in proof else "UNPROVEN","proof_text":proof,"evidence_digest":hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()})
    if len(rows)!=120 or [r["id"] for r in rows]!=list(range(1,121)): raise SystemExit("registry must contain ids 1..120")
    body={"schema_version":"alina.event_intelligence_status.v1","source":str(Path(a.source)),"items":rows,"summary":{s:sum(r["status"]==s for r in rows) for s in ["IMPLEMENTED_AND_WIRED","IMPLEMENTED_BUT_PARTIAL","IMPLEMENTED_BUT_NOT_WIRED","BROKEN","MISSING","NOT_APPLICABLE"]}}
    body["registry_digest"]=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    Path(a.output).write_text(json.dumps(body,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":a.output,"items":len(rows),"registry_digest":body["registry_digest"]},sort_keys=True))
if __name__=="__main__": main()
