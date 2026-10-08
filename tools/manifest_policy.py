#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

STATUSES = {"SAFE", "PARTIAL", "STALE", "REJECT", "NO_DATA"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_STRATEGY_FAMILIES = {
    "arbitrage",
    "copy_vault",
    "cross_venue_dislocation",
    "lead_lag",
}
REQUIRED = (
    "dataset_id",
    "family",
    "venue",
    "symbol",
    "start_ts_ms",
    "end_ts_ms",
    "sha256",
    "bytes",
    "event_count",
    "collector_version",
    "source",
)

_FATAL_COUNTERS = (
    "gap_count",
    "regression_count",
    "missing_timestamp_count",
    "missing_monotonic_count",
    "desync_count",
)

_MATCHED_RECONCILIATION_FAMILIES = {
    "agg_trades",
    "trades",
    "fills",
    "userfills",
    "user_fills",
}
_CONTINUITY_RECONCILIATION = {
    "MATCHED",
    "SOURCE_CONTINUITY_VERIFIED",
}
_SNAPSHOT_RECONCILIATION = {
    "MATCHED",
    "SNAPSHOT_VERIFIED",
}


def is_official_historical_archive(manifest: Mapping[str, Any]) -> bool:
    """True only for immutable first-party/public archive evidence.

    Historical archive rows cannot carry a local receive monotonic timestamp:
    treating that structurally unavailable field as corruption rejects otherwise
    replayable history. This exemption never applies to live/WebSocket capture.
    """
    source = str(manifest.get("source") or "").lower()
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    transports = {
        str(value).lower()
        for value in (provenance.get("transports") or [])
        if str(value).strip()
    }
    semantics = {
        str(value).lower()
        for value in (provenance.get("timestamp_semantics") or [])
        if str(value).strip()
    }
    return bool(
        manifest.get("asset_verified") is True
        and "official_archive" in source
        and transports
        and transports.issubset({"http", "https"})
        and "historical_exchange_time_only" in semantics
    )


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED:
        if key not in manifest:
            errors.append(f"MISSING:{key}")
        elif key in {"dataset_id", "family", "venue", "symbol", "collector_version", "source"} and not str(manifest.get(key) or "").strip():
            errors.append(f"INVALID:{key}")

    if manifest.get("quality_status") not in STATUSES:
        errors.append("INVALID:quality_status")
    digest = str(manifest.get("sha256") or "").lower()
    if not _SHA256.fullmatch(digest):
        errors.append("INVALID:sha256")

    start = _int(manifest.get("start_ts_ms"))
    end = _int(manifest.get("end_ts_ms"))
    size = _int(manifest.get("bytes"))
    count = _int(manifest.get("event_count"))
    if start is None or start < 0:
        errors.append("INVALID:start_ts_ms")
    if end is None or end < 0:
        errors.append("INVALID:end_ts_ms")
    if start is not None and end is not None and end < start:
        errors.append("INVALID:time_range")
    if size is None or size <= 0:
        errors.append("INVALID:bytes")
    if count is None or count < 0:
        errors.append("INVALID:event_count")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("MISSING:provenance")
    else:
        if provenance.get("public_data_only") is not True:
            errors.append("INVALID:public_data_only")
        if provenance.get("authenticated") is not False:
            errors.append("INVALID:authenticated")
        if provenance.get("real_execution") is not False:
            errors.append("INVALID:real_execution")

    integrity = manifest.get("integrity")
    if not isinstance(integrity, Mapping):
        errors.append("MISSING:integrity")
    reconciliation = manifest.get("reconciliation")
    if not isinstance(reconciliation, Mapping):
        errors.append("MISSING:reconciliation")
    for key in _FATAL_COUNTERS + ("duplicate_count",):
        if isinstance(integrity, Mapping):
            value = _int(integrity.get(key))
            if value is not None and value < 0:
                errors.append(f"INVALID_INTEGRITY:{key}")

    if str(manifest.get("family") or "").lower() == "external_events":
        integration = manifest.get("event_intelligence")
        if not isinstance(integration, Mapping):
            errors.append("MISSING:event_intelligence")
        elif not _valid_event_intelligence(integration):
            errors.append("INVALID:event_intelligence")
    return sorted(set(errors))


def _valid_event_intelligence(value: Mapping[str, Any]) -> bool:
    families = {
        str(item)
        for item in (value.get("linked_strategy_families") or [])
        if str(item)
    }
    digest = str(value.get("coverage_sha256") or "").lower()
    return bool(
        value.get("schema") == "alina.event_intelligence_integration.v1"
        and _int(value.get("idea_count")) == 120
        and value.get("coverage_complete") is True
        and _SHA256.fullmatch(digest)
        and families == _EVENT_STRATEGY_FAMILIES
        and value.get("proof_state") == "STRUCTURAL_ONLY"
        and value.get("proof_of_pnl_allowed") is False
        and value.get("paper_only") is True
        and value.get("read_only") is True
        and value.get("real_execution") is False
    )


def classify_manifest(manifest: Mapping[str, Any]) -> tuple[str, list[str]]:
    errors = validate_manifest(manifest)
    if errors:
        return "REJECT", errors

    event_count = int(manifest["event_count"])
    if event_count == 0:
        return "NO_DATA", ["NO_EVENTS"]

    integrity = manifest["integrity"]
    reasons: list[str] = []
    historical_archive = is_official_historical_archive(manifest)
    for key in _FATAL_COUNTERS:
        value = _int(integrity.get(key))
        # Local monotonic receive time is mandatory for live causal capture but
        # does not exist in an immutable historical exchange archive. Exchange
        # chronology is verified separately by replay inspection.
        if key == "missing_monotonic_count" and historical_archive:
            continue
        if value is None:
            reasons.append(f"MISSING_INTEGRITY:{key}")
        elif value > 0:
            reasons.append(f"FATAL_INTEGRITY:{key}={value}")

    duplicate_count = _int(integrity.get("duplicate_count"))
    if duplicate_count is None:
        reasons.append("MISSING_INTEGRITY:duplicate_count")
    elif duplicate_count > 0 and integrity.get("duplicates_deduped") is not True:
        reasons.append(f"DUPLICATES_NOT_DEDUPED:{duplicate_count}")

    if manifest.get("asset_verified") is not True:
        reasons.append("ASSET_NOT_VERIFIED")
    if manifest.get("validation_allowed") is True and manifest.get("replay_compatible") is not True:
        reasons.append("VALIDATION_WITHOUT_REPLAY_COMPATIBILITY")
    if manifest.get("replay_compatible") is not True:
        reasons.append("REPLAY_COMPATIBILITY_NOT_PROVEN")
    elif not str(manifest.get("replay_schema_version") or "").strip():
        reasons.append("REPLAY_SCHEMA_NOT_PROVEN")
    elif not str(manifest.get("replay_reason") or "").strip():
        reasons.append("REPLAY_RECEIPT_NOT_PROVEN")

    if str(manifest.get("family") or "").lower() == "external_events":
        runtime = manifest.get("event_intelligence_runtime")
        if not isinstance(runtime, Mapping):
            reasons.append("EVENT_INTELLIGENCE_RUNTIME_EVIDENCE_MISSING")
        elif not (
            runtime.get("schema") == "alina.event_intelligence_runtime_evidence.v1"
            and _SHA256.fullmatch(str(runtime.get("runtime_evidence_sha256") or "").lower())
            and _int(runtime.get("accepted_event_count")) is not None
            and _int(runtime.get("accepted_event_count")) >= 0
            and _SHA256.fullmatch(str(runtime.get("economic_research_sha256") or "").lower())
            and runtime.get("economic_research_state") in {"UNMEASURABLE", "REQUIRES_SCOREBOARD"}
            and _SHA256.fullmatch(str(runtime.get("market_response_sha256") or "").lower())
            and runtime.get("market_response_state") in {"UNMEASURABLE", "REQUIRES_SCOREBOARD"}
            and _SHA256.fullmatch(str(runtime.get("research_protocol_sha256") or "").lower())
            and runtime.get("research_protocol_state") in {"UNMEASURABLE", "REQUIRES_SCOREBOARD"}
            and runtime.get("proof_state") == "STRUCTURAL_ONLY"
            and runtime.get("proof_of_pnl_allowed") is False
        ):
            reasons.append("EVENT_INTELLIGENCE_RUNTIME_EVIDENCE_INVALID")

    trade_family = str(manifest.get("family") or "").lower() in {
        "trades", "agg_trades", "fills", "userfills", "user_fills",
        "copy_vault_fills",
    }
    if trade_family:
        trade_count = _int(manifest.get("trade_count"))
        unique_trade_count = _int(manifest.get("unique_trade_count"))
        if (
            manifest.get("trade_count_exact") is not True
            or trade_count is None
            or trade_count < 0
            or trade_count > event_count
        ):
            reasons.append("TRADE_COUNT_NOT_EXACT")
        if (
            manifest.get("unique_trade_count_exact") is not True
            or unique_trade_count is None
            or unique_trade_count < 0
            or (trade_count is not None and unique_trade_count > trade_count)
        ):
            reasons.append("UNIQUE_TRADE_COUNT_NOT_EXACT")

    reconciliation = manifest["reconciliation"]
    reconciliation_status = str(reconciliation.get("status") or "UNVERIFIED").upper()
    family = str(manifest.get("family") or "").lower()
    transports = set()
    provenance = manifest.get("provenance")
    if isinstance(provenance, Mapping):
        raw_transports = provenance.get("transports")
        if isinstance(raw_transports, list):
            transports = {str(value).lower() for value in raw_transports if str(value).strip()}

    if family in _MATCHED_RECONCILIATION_FAMILIES:
        if historical_archive:
            if reconciliation_status not in {"MATCHED", "SOURCE_ARCHIVE_VERIFIED"}:
                reasons.append("RECONCILIATION_ARCHIVE_VERIFICATION_REQUIRED")
        elif reconciliation_status not in _CONTINUITY_RECONCILIATION:
            reasons.append("RECONCILIATION_MATCH_REQUIRED")
    elif (
        family in {"copy_vault_positions", "copy_vault_selection"}
        and transports
        and transports.issubset({"http", "https"})
        and "receive_observation_time_only" in {
            str(value).lower()
            for value in (provenance.get("timestamp_semantics") or [])
        }
    ):
        if reconciliation_status not in _SNAPSHOT_RECONCILIATION:
            reasons.append(f"RECONCILIATION_{reconciliation_status}")
    elif family in {"instrument_metadata", "open_interest", "funding_settlement"} and transports and transports.issubset({"http", "https"}):
        if reconciliation_status not in _SNAPSHOT_RECONCILIATION:
            reasons.append(f"RECONCILIATION_{reconciliation_status}")
    elif "websocket" in transports:
        if reconciliation_status not in _CONTINUITY_RECONCILIATION:
            reasons.append(f"RECONCILIATION_{reconciliation_status}")
    elif reconciliation_status != "MATCHED":
        reasons.append(f"RECONCILIATION_{reconciliation_status}")

    required = {str(x) for x in (manifest.get("required_channels") or []) if str(x)}
    observed = {str(x) for x in (manifest.get("observed_channels") or []) if str(x)}
    missing_channels = sorted(required - observed)
    if missing_channels:
        reasons.append("MISSING_CHANNELS:" + ",".join(missing_channels))

    cost = manifest.get("cost_model")
    if isinstance(cost, Mapping) and cost.get("applicable") is True and cost.get("ready") is not True:
        reasons.append("COST_MODEL_NOT_READY")

    freshness = manifest.get("freshness")
    if isinstance(freshness, Mapping) and freshness.get("stale") is True:
        return "STALE", reasons + ["STALE"]

    fatal = any(reason.startswith("FATAL_INTEGRITY:") for reason in reasons)
    if fatal:
        return "REJECT", reasons
    if reasons:
        return "PARTIAL", reasons
    return "SAFE", []


def verify_asset(manifest: Mapping[str, Any], asset_path: str | Path) -> tuple[bool, str]:
    path = Path(asset_path)
    if not path.is_file():
        return False, "ASSET_MISSING"
    expected_size = _int(manifest.get("bytes"))
    if expected_size is None or path.stat().st_size != expected_size:
        return False, "ASSET_SIZE_MISMATCH"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != str(manifest.get("sha256") or "").lower():
        return False, "ASSET_SHA256_MISMATCH"
    return True, "MATCHED"


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "REQUIRED",
    "STATUSES",
    "classify_manifest",
    "load_json",
    "validate_manifest",
    "verify_asset",
    "is_official_historical_archive",
]
