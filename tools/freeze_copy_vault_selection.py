#!/usr/bin/env python3
"""Freeze the complete qualifying public Hyperliquid vault universe for hosted lanes."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"src"))

import collecter_vaults as CV  # noqa: E402


def build_selection(payload: Any, *, now_ms: int | None=None) -> dict[str,Any]:
    selected_at_ms=int(time.time()*1000) if now_ms is None else int(now_ms)
    raw_count=len(payload) if isinstance(payload,list) else 0
    rows=CV.parser_univers_public(
        payload,
        now_ms=selected_at_ms,
        min_tvl_usd=0.0,
        min_age_days=0.0,
        max_vaults=max(1,raw_count),
    )
    if not rows:
        raise RuntimeError("public Copy-Vault observation universe is empty")
    return {
        "schema":"alina.copy_vault_selection.v2",
        "selected_at_ms":selected_at_ms,
        "source":CV.URL_VAULTS,
        "filters":{
            "min_tvl_usd":0.0,
            "min_age_days":0.0,
            "relationship":"normal",
            "is_closed":False,
            "max_vaults":None,
        },
        "raw_public_rows":raw_count,
        "vault_count":len(rows),
        "vaults":rows,
        "observation_only":True,
        "read_only":True,
        "real_execution":False,
    }


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    payload=CV._get_vaults_public()
    selection=build_selection(payload)
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(selection,indent=2,sort_keys=True)+"\n").encode()
    out.write_bytes(raw)
    print(json.dumps({
        "path":str(out),
        "vault_count":selection["vault_count"],
        "lane_count":(int(selection["vault_count"])+CV.MAX_UNIQUE_USERS_PER_IP-1)//CV.MAX_UNIQUE_USERS_PER_IP
            if hasattr(CV,"MAX_UNIQUE_USERS_PER_IP") else (int(selection["vault_count"])+9)//10,
        "sha256":hashlib.sha256(raw).hexdigest(),
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
