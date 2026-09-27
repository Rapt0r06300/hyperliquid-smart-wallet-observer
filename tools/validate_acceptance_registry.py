#!/usr/bin/env python3
"""Fail-closed validator for the canonical acceptance-gate registry."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import yaml

REQUIRED={"id","owner","input_evidence","validator","failure_code","blocks"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--registry",default="config/acceptance_criteria.yaml")
    args=p.parse_args()
    doc=yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))
    if not isinstance(doc,dict) or doc.get("schema_version")!="alina.acceptance_registry.v1":
        raise SystemExit("unsupported acceptance registry")
    gates=doc.get("gates")
    if not isinstance(gates,list) or not gates:
        raise SystemExit("acceptance registry has no gates")
    ids=[]
    for gate in gates:
        if not isinstance(gate,dict) or REQUIRED-set(gate):
            raise SystemExit("gate missing required fields")
        if gate["id"] in ids:
            raise SystemExit("duplicate gate id")
        if not isinstance(gate["input_evidence"],list) or not gate["input_evidence"]:
            raise SystemExit("gate input_evidence must be non-empty")
        if not isinstance(gate["blocks"],list) or not gate["blocks"]:
            raise SystemExit("gate blocks must be non-empty")
        ids.append(gate["id"])
    print(json.dumps({"schema_version":doc["schema_version"],"gate_count":len(gates),"gate_ids":ids},sort_keys=True))
if __name__=="__main__":
    raise SystemExit(main())
