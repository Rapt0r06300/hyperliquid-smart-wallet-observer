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
REPLAYABLE_FAMILIES={"capacity_tape","trades","agg_trades","bbo","l2book","l2","book","funding","funding_settlement","open_interest","fills","userfills","user_fills","copy_vault_fills","copy_vault_l2","copy_vault_positions","copy_vault_selection","copy_vault_snapshot","external_events","activeassetctx","instrument_metadata","mark_price","ticker"}
VERIFIER_VERSION="alina.replay.compatibility.v7"


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
    raw = row.get("raw_payload")
    if not isinstance(raw, str) or not raw:
        return None
    # The old collector did not persist request_type for HTTP observations.
    # Inspect the immutable HTTP response *and* its provenance instead of
    # demanding modern metadata that cannot be reconstructed retroactively.
    import hashlib
    if row.get("raw_sha256") != hashlib.sha256(raw.encode("utf-8")).hexdigest():
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if family == "copy_vault_positions":
        if (
            provenance.get("request_type") not in {None, "clearinghouseState"}
            or not isinstance(payload.get("assetPositions"), list)
        ):
            return None
        if provenance.get("request_type") is None:
            if provenance.get("url") != "https://api.hyperliquid.xyz/info":
                return None
            summary = row.get("parsed_summary")
            if not isinstance(summary, Mapping) or summary.get("position_count") != len(payload["assetPositions"]):
                return None
    else:
        if not isinstance(payload.get("selection"), Mapping) or not isinstance(payload.get("filters"), Mapping):
            return None
        if provenance.get("selection_causal") is not True:
            if provenance.get("url") != "https://stats-data.hyperliquid.xyz/Mainnet/vaults":
                return None
            summary = row.get("parsed_summary")
            if not isinstance(summary, Mapping) or summary.get("observation_only") is not True:
                return None
            if summary.get("selected_at_ms") != row.get("received_ts_ms"):
                return None
    recv = row.get("received_ts_ms")
    monotonic = row.get("local_monotonic_ns")
    if type(recv) is not int or recv <= 0 or type(monotonic) is not int or monotonic <= 0:
        return None
    return recv


def _proof_of_active_asset_context(row: Mapping[str, Any], manifest: Mapping[str, Any]) -> int | None:
    """Use genuine receive-time observation for timestamp-free Hyperliquid context."""
    import hashlib
    if (
        str(manifest.get("source") or "") != "hyperliquid_public_ws"
        or row.get("source_id") != "hyperliquid_public_ws"
        or row.get("channel") != "activeAssetCtx"
        or str(row.get("event_kind") or "").upper() != "SNAPSHOT"
        or row.get("exchange_ts_ms") is not None
        or row.get("real_execution") is not False
    ):
        return None
    provenance = row.get("provenance")
    if not isinstance(provenance, Mapping) or any((
        provenance.get("transport") != "websocket",
        provenance.get("access") != "read_only",
        provenance.get("authenticated") is not False,
        provenance.get("timestamp_semantics") != "receive_observation_time_only",
    )):
        return None
    raw = row.get("raw_payload")
    if not isinstance(raw, str) or not raw:
        return None
    if row.get("raw_sha256") != hashlib.sha256(raw.encode("utf-8")).hexdigest():
        return None
    try:
        source = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(source, Mapping) or source.get("channel") != "activeAssetCtx":
        return None
    data = source.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("ctx"), Mapping):
        return None
    recv = row.get("received_ts_ms")
    mono = row.get("local_monotonic_ns")
    if type(recv) is not int or recv <= 0 or type(mono) is not int or mono <= 0:
        return None
    return recv


def _verified_capacity_lineage(row: Mapping[str, Any]) -> bool:
    """Verify an individual derived capacity record's immutable L2 references.

    This proves only replayability of the *derived tape*, not the existence,
    completeness or SAFE classification of the parent L2 shard.
    """
    import hashlib
    import re
    if (
        row.get("channel") != "capacity_tape"
        or row.get("real_execution") is not False
        or str(row.get("event_kind") or "").upper() != "SNAPSHOT"
        or row.get("exchange_ts_ms") is None
    ):
        return False
    provenance = row.get("provenance")
    summary = row.get("parsed_summary")
    if not isinstance(provenance, Mapping) or not isinstance(summary, Mapping):
        return False
    if not (
        provenance.get("transport") == "derived"
        and provenance.get("access") == "read_only"
        and provenance.get("authenticated") is False
        and provenance.get("derived") is True
        and provenance.get("derived_from_family") == "l2Book"
        and provenance.get("raw_l2_source_of_truth") is True
    ):
        return False
    raw = row.get("raw_payload")
    if not isinstance(raw, str) or not raw:
        return False
    if row.get("raw_sha256") != hashlib.sha256(raw.encode("utf-8")).hexdigest():
        return False
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping) or payload.get("derived_from_family") != "l2Book":
        return False
    sha = str(summary.get("source_raw_l2_sha256") or "")
    book = str(summary.get("source_reconstructed_book_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(r"[0-9a-f]{64}", book):
        return False
    if (
        sha != str(payload.get("source_raw_l2_sha256") or "")
        or sha != str(provenance.get("source_raw_l2_sha256") or "")
        or book != str(payload.get("source_reconstructed_book_sha256") or "")
        or book != str(provenance.get("source_reconstructed_book_sha256") or "")
    ):
        return False
    identity = summary.get("source_l2_identity")
    if not isinstance(identity, Mapping):
        return False
    return (
        identity.get("raw_l2_sha256") == sha
        and identity.get("reconstructed_book_sha256") == book
        and identity.get("receive_monotonic_ns") == row.get("local_monotonic_ns")
        and identity.get("exchange_ts_ms") == row.get("exchange_ts_ms")
        and identity.get("sequence") == row.get("sequence")
    )


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
    receive_context = family == "activeassetctx"
    context_proven = 0
    context_observation_clocks: set[int] = set()
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
                if receive_context:
                    observed_ctx = _proof_of_active_asset_context(row, manifest)
                    if observed_ctx is not None:
                        context_proven += 1
                        context_observation_clocks.add(row["local_monotonic_ns"])
                        ts = float(observed_ctx)
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

                if family == "capacity_tape" and not _verified_capacity_lineage(row):
                    result["invalid_record_count"] += 1
                    continue
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

    result["receive_only_context_verified"] = bool(
        receive_context and result["record_count"] > 0
        and context_proven == result["record_count"]
        and len(context_observation_clocks) == result["record_count"]
        and result["invalid_record_count"] == 0
    )
    result["derived_capacity_lineage_verified"] = bool(
        family == "capacity_tape" and result["record_count"] > 0
        and result["invalid_record_count"] == 0
    )
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
