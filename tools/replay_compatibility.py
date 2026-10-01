#!/usr/bin/env python3
"""Strict replay compatibility inspection for immutable Dataset V2 assets."""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any, Mapping

TRADE_FAMILIES={"trades","agg_trades","fills","userfills","user_fills","copy_vault_fills"}
REPLAYABLE_FAMILIES={"trades","agg_trades","bbo","l2book","l2","book","funding","funding_settlement","open_interest","fills","userfills","user_fills","copy_vault_fills","copy_vault_l2","copy_vault_positions","copy_vault_selection","copy_vault_snapshot","external_events","activeassetctx","instrument_metadata","mark_price","ticker"}


def _open(path: Path):
    return gzip.open(path,"rt",encoding="utf-8") if path.name.endswith(".gz") else path.open(encoding="utf-8")


def _timestamp(row: Mapping[str, Any]) -> float | None:
    raw=row.get("exchange_ts_ms",row.get("timestamp_ms",row.get("ts_ms",row.get("timestamp"))))
    try:
        value=float(raw)
    except (TypeError,ValueError,OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0.0 else None


def _identity(row: Mapping[str, Any], manifest: Mapping[str, Any], ts: float) -> tuple[Any, ...] | None:
    price=row.get("price")
    size=row.get("size", row.get("qty"))
    if price is not None or size is not None:
        try:
            price_value=float(price)
            size_value=float(size)
        except (TypeError, ValueError, OverflowError):
            return None
        if (
            not math.isfinite(price_value)
            or not math.isfinite(size_value)
            or price_value <= 0.0
            or size_value <= 0.0
        ):
            return None
    native=row.get("trade_id") or row.get("id") or row.get("exec_id") or row.get("sequence")
    if native is not None and str(native):
        return (manifest.get("venue"), manifest.get("symbol"), "native", str(native))
    side=row.get("side")
    if side is None or price is None or size is None:
        return None
    if not str(side).strip():
        return None
    return (
        manifest.get("venue"), manifest.get("symbol"), "composite", ts,
        str(side), str(price), str(size),
    )


def inspect_asset(path: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    p=Path(path)
    family=str(manifest.get("family") or "").lower()
    result={"record_count":0,"trade_count":0,"trade_count_exact":True,
            "invalid_record_count":0,"out_of_order_count":0,"duplicate_count":0,
            "gap_count":int((manifest.get("integrity") or {}).get("gap_count") or 0),
            "replay_compatible":False,"replay_schema_version":"alina.replay.v2",
            "replay_reason":"UNVERIFIED"}
    last: float | None=None
    seen:set[tuple[Any,...]]=set()
    try:
        with _open(p) as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row=json.loads(line)
                except (TypeError,ValueError,json.JSONDecodeError):
                    result["invalid_record_count"]+=1
                    continue
                if not isinstance(row,Mapping):
                    result["invalid_record_count"]+=1
                    continue
                result["record_count"]+=1
                ts=_timestamp(row)
                if ts is None:
                    result["invalid_record_count"]+=1
                    continue
                if last is not None and ts < last:
                    result["out_of_order_count"]+=1
                last=ts
                identity=_identity(row,manifest,ts)
                if identity is None:
                    result["invalid_record_count"]+=1
                    if family in TRADE_FAMILIES:
                        result["trade_count_exact"]=False
                    continue
                if identity in seen:
                    result["duplicate_count"]+=1
                else:
                    seen.add(identity)
                    if family in TRADE_FAMILIES:
                        parsed=row.get("parsed_summary")
                        batch_count=None
                        if isinstance(parsed,Mapping):
                            for key in ("event_count","fill_count"):
                                try:
                                    value=parsed.get(key)
                                    if value is not None and not isinstance(value,bool):
                                        batch_count=max(0,int(value))
                                        break
                                except (TypeError,ValueError,OverflowError):
                                    pass
                        result["trade_count"]+=(batch_count if batch_count is not None else 1)
    except (OSError,EOFError,UnicodeError,gzip.BadGzipFile):
        result["replay_reason"]="TRUNCATED_OR_UNREADABLE"
        return result
    if result["record_count"]<=0:
        result["replay_reason"]="NO_RECORDS"
    elif result["invalid_record_count"]>0:
        result["replay_reason"]="INVALID_RECORD"
    elif result["out_of_order_count"]>0:
        result["replay_reason"]="OUT_OF_ORDER"
    elif result["gap_count"]>0:
        result["replay_reason"]="GAP"
    elif result["duplicate_count"]>0:
        result["replay_reason"]="DUPLICATES_PRESENT"
    elif family in TRADE_FAMILIES and result["trade_count_exact"] is not True:
        result["replay_reason"]="TRADE_COUNT_NOT_EXACT"
    elif family not in REPLAYABLE_FAMILIES:
        result["replay_reason"]="NO_REPLAY_ADAPTER"
    else:
        result["replay_compatible"]=True
        result["replay_reason"]="STRICT_PARSE_CHRONOLOGY_OK"
    return result
