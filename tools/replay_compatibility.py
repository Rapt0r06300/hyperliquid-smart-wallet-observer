#!/usr/bin/env python3
"""Strict replay compatibility inspection for immutable Dataset V2 assets."""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.backfill_exact_trade_counts import _native_trade_keys, _summary_trade_count
except ModuleNotFoundError:
    from backfill_exact_trade_counts import _native_trade_keys, _summary_trade_count

TRADE_FAMILIES={"trades","agg_trades","fills","userfills","user_fills","copy_vault_fills"}
REPLAYABLE_FAMILIES={"trades","agg_trades","bbo","l2book","l2","book","funding","funding_settlement","open_interest","fills","userfills","user_fills","copy_vault_fills","copy_vault_l2","copy_vault_positions","copy_vault_selection","copy_vault_snapshot","external_events","activeassetctx","instrument_metadata","mark_price","ticker"}
VERIFIER_VERSION="alina.replay.compatibility.v4"


def _open(path: Path):
    return gzip.open(path,"rt",encoding="utf-8") if path.name.endswith(".gz") else path.open(encoding="utf-8")


def _timestamp(row: Mapping[str, Any]) -> float | None:
    raw=row.get("exchange_ts_ms",row.get("timestamp_ms",row.get("ts_ms",row.get("timestamp"))))
    try:
        value=float(raw)
    except (TypeError,ValueError,OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0.0 else None


_RECEIVE_ONLY_COPY_SOURCES = {
    "copy_vault_positions": "hyperliquid_public_info",
    "copy_vault_selection": "hyperliquid_public_vaults",
}


def _proof_of_receive_only_snapshot(
    row: Mapping[str, Any], family: str, manifest: Mapping[str, Any]
) -> int | None:
    """Strictly verify *observed* HTTP state; never synthesize exchange events."""
    if (
        family not in _RECEIVE_ONLY_COPY_SOURCES
        or manifest.get("source") != _RECEIVE_ONLY_COPY_SOURCES[family]
        or row.get("source_id") != _RECEIVE_ONLY_COPY_SOURCES[family]
        or str(row.get("channel") or "").lower() != family
        or str(row.get("event_kind") or "").upper() != "SNAPSHOT"
        or row.get("exchange_ts_ms") is not None
        or row.get("real_execution") is not False
    ):
        return None
    provenance = row.get("provenance")
    if not isinstance(provenance, Mapping) or (
        provenance.get("transport") != "https"
        or provenance.get("access") not in {"read_only", "public_read_only"}
        or provenance.get("authenticated") is not False
    ):
        return None
    if family == "copy_vault_positions":
        if provenance.get("request_type") != "clearinghouseState":
            return None
    elif provenance.get("selection_causal") is not True:
        return None
    raw = row.get("raw_payload")
    if not isinstance(raw, str) or not raw:
        return None
    # Hash the actual envelope raw payload: a mislabeled/corrupt snapshot fails.
    import hashlib
    if row.get("raw_sha256") != hashlib.sha256(raw.encode("utf-8")).hexdigest():
        return None
    recv = row.get("received_ts_ms")
    monotonic = row.get("local_monotonic_ns")
    if type(recv) is not int or recv <= 0 or type(monotonic) is not int or monotonic <= 0:
        return None
    return recv


def inspect_asset(path: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Verify parseability and causal chronology without inventing evidence.

    Trade-bearing families reuse the exact-count parser's venue-aware identities,
    including normalized TickEnvelope raw_payload. Non-trade market-data families
    require valid JSON plus exchange timestamps/chronology; they are not rejected
    merely because they do not carry a trade id.
    """
    p=Path(path)
    family=str(manifest.get("family") or "").lower()
    venue=str(manifest.get("venue") or "unknown")
    symbol=str(manifest.get("symbol") or "")
    result={
        "record_count":0,
        "trade_count":0,
        "trade_count_exact":True,
        "invalid_record_count":0,
        "out_of_order_count":0,
        "duplicate_count":0,
        "gap_count":int((manifest.get("integrity") or {}).get("gap_count") or 0),
        "replay_compatible":False,
        "replay_schema_version":"alina.replay.v2",
        "replay_reason":"UNVERIFIED",
        "verifier_version":VERIFIER_VERSION,
    }
    last: float | None=None
    seen:set[str]=set()
    receive_only = family in _RECEIVE_ONLY_COPY_SOURCES
    verified_observations = 0
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
                if receive_only:
                    observed = _proof_of_receive_only_snapshot(row, family, manifest)
                    if observed is not None:
                        verified_observations += 1
                        ts = float(observed)
                    else:
                        ts = None
                if ts is None:
                    result["invalid_record_count"]+=1
                    if family in TRADE_FAMILIES:
                        result["trade_count_exact"]=False
                    continue
                if last is not None and ts < last:
                    result["out_of_order_count"]+=1
                last=ts

                if family not in TRADE_FAMILIES:
                    continue

                identities=_native_trade_keys(
                    row,
                    venue=venue,
                    family=family,
                    symbol=symbol,
                )
                if identities is None:
                    # Legacy normalized batch envelopes may retain only a
                    # causal sequence plus an exact parsed event count. Preserve
                    # that already-supported replay path without fabricating
                    # per-trade identities.
                    batch_count=_summary_trade_count(row)
                    sequence=row.get("sequence")
                    if (
                        batch_count is not None
                        and batch_count > 0
                        and sequence is not None
                        and str(sequence) != ""
                    ):
                        result["trade_count"]+=batch_count
                        envelope_identity=f"{venue}|{family}|{symbol}|sequence|{sequence}"
                        if envelope_identity in seen:
                            result["duplicate_count"]+=1
                        else:
                            seen.add(envelope_identity)
                        continue
                    result["invalid_record_count"]+=1
                    result["trade_count_exact"]=False
                    continue

                result["trade_count"]+=len(identities)
                for identity in identities:
                    if identity in seen:
                        result["duplicate_count"]+=1
                    else:
                        seen.add(identity)
    except (OSError,EOFError,UnicodeError,gzip.BadGzipFile):
        result["replay_reason"]="TRUNCATED_OR_UNREADABLE"
        return result

    result["receive_only_snapshot_verified"] = bool(
        receive_only and verified_observations == result["record_count"]
        and verified_observations > 0
        and result["invalid_record_count"] == 0
    )
    if result["record_count"]<=0:
        result["replay_reason"]="NO_RECORDS"
    elif result["invalid_record_count"]>0:
        result["replay_reason"]="INVALID_RECORD"
    elif result["out_of_order_count"]>0:
        result["replay_reason"]="OUT_OF_ORDER"
    elif result["gap_count"]>0:
        result["replay_reason"]="GAP"
    elif family in TRADE_FAMILIES and result["trade_count_exact"] is not True:
        result["replay_reason"]="TRADE_COUNT_NOT_EXACT"
    elif family in TRADE_FAMILIES and result["duplicate_count"]>0:
        result["replay_reason"]="DUPLICATES_PRESENT"
    elif family not in REPLAYABLE_FAMILIES:
        result["replay_reason"]="NO_REPLAY_ADAPTER"
    else:
        result["replay_compatible"]=True
        result["replay_reason"]="STRICT_PARSE_CHRONOLOGY_OK"
    return result
