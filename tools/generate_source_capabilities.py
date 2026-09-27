#!/usr/bin/env python3
"""Generate a conservative source-capability matrix from the current repository."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

VENUES=("hyperliquid","binance","bybit","okx","gate","bitget")
CAPABILITIES=("trades","bbo","l2","clock_sync","recovery","replay_adapter")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default="src/hl_observer")
    p.add_argument("--output",default="docs/source-capability-matrix.json")
    a=p.parse_args()
    root=Path(a.root)
    files=[path for path in root.rglob("*") if path.is_file() and path.suffix in {".py",".yml",".yaml",".json"}]
    rows=[]
    for venue in VENUES:
        tokens=[venue,venue.replace("_","-")]
        matches=[str(path) for path in files if any(token in path.name.lower() or token in path.read_text(encoding="utf-8",errors="ignore").lower()[:200000] for token in tokens)]
        evidence=sorted(set(matches))[:100]
        caps={}
        for cap in CAPABILITIES:
            keyword_map={"trades":["trade","fills"],"bbo":["bbo","best_bid","best_ask"],"l2":["l2","orderbook","depth"],"clock_sync":["clock","offset","rtt"],"recovery":["reconnect","backfill","resume"],"replay_adapter":["replay","normaliz"]}
            hits=[path for path in evidence if any(k in Path(path).read_text(encoding="utf-8",errors="ignore").lower() for k in keyword_map[cap])]
            caps[cap]={"status":"FILE_PRESENT" if hits else "MISSING","evidence":sorted(hits)[:20]}
        rows.append({"venue":venue,"status":"FILE_PRESENT" if evidence else "MISSING","evidence_files":evidence,"capabilities":caps})
    body={"schema_version":"alina.source_capability_matrix.v1","source_root":a.root,"venues":rows,"policy":"FILE_PRESENT is not IMPORT_OK, COLLECTOR_ACTIVE, SOURCE_HEALTHY, REPLAY_COMPATIBLE or PNL_READY"}
    body["matrix_digest"]=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    Path(a.output).write_text(json.dumps(body,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":a.output,"venues":len(rows),"matrix_digest":body["matrix_digest"]},sort_keys=True))
if __name__=="__main__": main()
