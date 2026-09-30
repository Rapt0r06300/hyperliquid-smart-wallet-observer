#!/usr/bin/env python3
"""Validate the machine-readable normative proof gate registry."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--path",default="docs/normative-gate-registry.json")
    a=p.parse_args()
    body=json.loads(Path(a.path).read_text(encoding="utf-8"))
    if body.get("schema")!="alina.normative_gate_registry.v1":
        raise SystemExit("unsupported gate registry schema")
    gates=body.get("gates")
    if not isinstance(gates,list) or len(gates)<9:
        raise SystemExit("incomplete gate registry")
    ids=[row.get("gate_id") for row in gates]
    if len(ids)!=len(set(ids)):
        raise SystemExit("duplicate gate identity")
    required={"gate_id","owner","input_evidence","validator","failure_code","blocks"}
    for row in gates:
        if set(row) != required or not all(row.get(key) for key in required):
            raise SystemExit(f"invalid gate row: {row.get('gate_id')}")
    expected=hashlib.sha256(json.dumps(gates,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if body.get("registry_digest")!=expected:
        raise SystemExit("gate registry digest mismatch")
    if body.get("paper_only") is not True or body.get("read_only") is not True or body.get("real_execution") is not False:
        raise SystemExit("unsafe gate registry flags")
    print(json.dumps({"gate_count":len(gates),"registry_digest":expected},sort_keys=True))
if __name__=="__main__": main()
