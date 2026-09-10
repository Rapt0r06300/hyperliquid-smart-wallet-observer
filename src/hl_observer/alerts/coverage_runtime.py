"""Read bounded collector evidence without starting collectors or writing state."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.alerts.coverage import (
    build_source_coverage_receipt,
    validate_source_coverage_universe,
)
from hl_observer.alerts.coverage_completeness import build_coverage_completeness_attestation

ALLMIDS_CAPTURE_SCHEMA = "hypersmart.allmids_coverage_capture.v1"
ALLMIDS_SOURCE = "hyperliquid-info-allmids"
ALLMIDS_RELATIVE_PATH = Path("runtime/data/hl_allmids.json")
MAX_CACHE_BYTES = 1_048_576


def cache_sample_hash(payload: Mapping[str, Any]) -> str:
    sample = {key: value for key, value in payload.items() if key != "coverage_capture"}
    encoded = json.dumps(sample, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _read_allmids(root: Path, desired: dict, now_ms: int) -> tuple[dict | None, dict]:
    path = root / ALLMIDS_RELATIVE_PATH
    diagnostic: dict[str, Any] = {
        "source_id": ALLMIDS_SOURCE,
        "path": ALLMIDS_RELATIVE_PATH.as_posix(),
        "validation_scope": "LOCAL_COLLECTOR_RESPONSE_NOT_GLOBAL_COVERAGE",
        "connection_semantics": "RECENT_SUCCESSFUL_HTTP_RESPONSE_NOT_PERSISTENT_SOCKET",
        "state": "MISSING", "reason": "CACHE_MISSING", "sha256": None,
        "age_ms": None,
    }
    try:
        # No locks, directory creation or network calls on this read-only path.
        for item in (path, *path.parents):
            if item == root:
                break
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise ValueError("CACHE_LINK_REFUSED")
        if not path.is_file():
            return None, diagnostic
        with path.open("rb") as handle:
            raw = handle.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            raise ValueError("CACHE_TOO_LARGE")
        diagnostic["sha256"] = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("CACHE_NOT_OBJECT")
        capture = payload.get("coverage_capture")
        if not isinstance(capture, dict):
            raise ValueError("CACHE_CAPTURE_MISSING")
        if capture.get("schema_version") != ALLMIDS_CAPTURE_SCHEMA:
            raise ValueError("CACHE_CAPTURE_SCHEMA_INVALID")
        if capture.get("data_mode") != "LIVE":
            raise ValueError("NON_LIVE_CAPTURE")
        if (capture.get("source_id") != ALLMIDS_SOURCE
                or capture.get("endpoint") != "https://api.hyperliquid.xyz/info"
                or capture.get("request_type") != "allMids"
                or capture.get("paper_read_only") is not True
                or capture.get("real_execution") is not False):
            raise ValueError("CACHE_CAPTURE_PROVENANCE_INVALID")
        timestamp = payload.get("ts_ms")
        if type(timestamp) is not int or not 0 <= timestamp <= now_ms:
            raise ValueError("CACHE_TIMESTAMP_INVALID_OR_FUTURE")
        if capture.get("fetched_at_ms") != timestamp:
            raise ValueError("CACHE_CAPTURE_TIMESTAMP_MISMATCH")
        latency = capture.get("transport_latency_ms")
        if not _valid_number(latency):
            raise ValueError("CACHE_LATENCY_INVALID")
        mids = payload.get("mids")
        if (not isinstance(mids, dict) or not mids
                or type(payload.get("n")) is not int or payload["n"] != len(mids)
                or any(not key or not _valid_number(value) or value <= 0
                       for key, value in mids.items())):
            raise ValueError("CACHE_PRICES_INVALID")
        if capture.get("sample_hash") != cache_sample_hash(payload):
            raise ValueError("CACHE_SAMPLE_HASH_MISMATCH")
        age = now_ms - timestamp
        fresh = age <= desired["freshness_slo_ms"]
        health = "STALE" if not fresh else (
            "HEALTHY" if latency <= desired["latency_slo_ms"] else "DEGRADED"
        )
        diagnostic.update(state="OBSERVED", reason=health, age_ms=age)
        return {
            "source_id": ALLMIDS_SOURCE,
            "connection_state": "CONNECTED" if fresh else "UNKNOWN",
            "source_status": health,
            # Public access is not proof of a licence or redistribution entitlement.
            "entitlement": "UNKNOWN", "license_class": "UNKNOWN",
            "latency_ms": latency,
            "last_successful_refresh_ms": timestamp,
            "last_validated_at_ms": now_ms,
            "validation_evidence_refs": [
                f"local-cache:{ALLMIDS_RELATIVE_PATH.as_posix()}#sha256={diagnostic['sha256']}"
            ],
        }, diagnostic
    except (OSError, ValueError, UnicodeDecodeError, OverflowError) as exc:
        diagnostic.update(state="REJECTED", reason=str(exc)[:200])
        return None, diagnostic


def read_runtime_coverage_observations(
    root: str | Path, universe: Mapping[str, Any], *, evaluated_at_ms: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if type(evaluated_at_ms) is not int or evaluated_at_ms < 0:
        raise ValueError("RUNTIME_COVERAGE_CLOCK_INVALID")
    declared = validate_source_coverage_universe(universe)
    desired = {source["source_id"]: source for group in declared["coverage_classes"]
               for source in group["desired_sources"]}
    if ALLMIDS_SOURCE not in desired:
        return [], []
    observation, diagnostic = _read_allmids(
        Path(root).resolve(), desired[ALLMIDS_SOURCE], evaluated_at_ms,
    )
    return ([observation] if observation is not None else []), [diagnostic]


def build_runtime_coverage_report(
    root: str | Path, universe: Mapping[str, Any], *, evaluated_at_ms: int,
) -> dict[str, Any]:
    observations, inputs = read_runtime_coverage_observations(
        root, universe, evaluated_at_ms=evaluated_at_ms,
    )
    receipt = build_source_coverage_receipt(
        universe, observations, evaluated_at_ms=evaluated_at_ms,
    )
    return {
        "schema_version": "hypersmart.source_coverage_report.v1",
        "coverage_receipt": receipt,
        "completeness_attestation": build_coverage_completeness_attestation(
            receipt, evaluated_at_ms=evaluated_at_ms,
        ),
        "runtime_inputs": inputs,
        "paper_read_only": True, "real_execution": False,
    }
