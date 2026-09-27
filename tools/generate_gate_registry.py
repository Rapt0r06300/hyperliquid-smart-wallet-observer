#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from hl_observer.control_plane.gate_registry import gate_contract

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="docs/normative-gate-registry.json")
    a=p.parse_args()
    target=Path(a.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(gate_contract(),sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(target),"registry_digest":gate_contract()["registry_digest"]},sort_keys=True))
if __name__=="__main__": main()
