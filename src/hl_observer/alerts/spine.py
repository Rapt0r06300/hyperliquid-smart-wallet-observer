"""Durable, local-only alert spine with one canonical writer.

Producers can only create immutable proposals in their own inbox. A single
deterministic writer validates and appends canonical events, then derives a
mutable dashboard projection from that append-only ledger. The module has no
network, shell, model or trading capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.alerts.freshness import project_alert_freshness
from hl_observer.collection.collecte_fiable import append_jsonl, ecrire_atomique

PROPOSAL_SCHEMA = "hypersmart.alert_proposal.v1"
EVENT_SCHEMA = "hypersmart.canonical_alert_event.v1"
PROJECTION_SCHEMA = "hypersmart.alert_projection.v1"
LEDGER_LATEST_SCHEMA = "hypersmart.alert_ledger_latest.v1"
SCORE_POLICY_VERSION = "hypersmart.alert_score.v1"
_PRODUCER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_EPOCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SEGMENT_RE = re.compile(
    r"^alerts\.(?P<first>\d{20})-(?P<last>\d{20})\."
    r"(?P<sha256>[0-9a-f]{64})\.jsonl$"
)
_DEFAULT_LEDGER_ROTATE_BYTES = 64 * 1024 * 1024
_MAX_HEADLINE = 1_000
_MAX_DEDUP_KEY = 256
_MAX_ENTITY_COUNT = 128
_MAX_EVIDENCE_REFS = 128
SOURCE_HEALTH_STATES = frozenset(
    {
        "HEALTHY",
        "DEGRADED",
        "STALE",
        "RATE_LIMITED",
        "AUTH_REQUIRED",
        "UNREACHABLE",
        "SEMANTIC_DRIFT",
        "COVERAGE_UNKNOWN",
    }
)
FRESHNESS_STATES = frozenset({"FRESH", "DEGRADED", "STALE", "UNKNOWN"})
IMMUTABLE_LIFECYCLE_STATES = ("DETECTED", "FETCHED", "VERIFIED", "ADMITTED")
PROJECTION_LIFECYCLE_STATES = frozenset(
    {"PROJECTED", "EXPIRED", "CORRECTED", "RETRACTED"}
)
SCORE_WEIGHTS_BPS: dict[str, int] = {
    "source_authority": 1_500,
    "source_directness": 1_250,
    "freshness": 1_250,
    "corroboration_independence": 1_000,
    "source_health": 1_000,
    "entity_resolution": 900,
    "event_specificity": 800,
    "research_relevance": 700,
    "contradiction_clarity": 600,
    "evidence_completeness": 500,
    "revision_stability": 300,
    "traceability": 200,
}
_FORBIDDEN_ORDER_KEYS = frozenset(
    {
        "execute",
        "exchange_order",
        "leverage",
        "order_intent",
        "private_key",
        "real_order",
        "signature",
    }
)


class AlertSpineError(RuntimeError):
    """Base class for fail-closed alert-spine errors."""


class AlertValidationError(AlertSpineError):
    """Raised when a producer proposal is not admissible."""


class CanonicalLedgerCorruption(AlertSpineError):
    """Raised when the append-only ledger cannot be replayed exactly."""


class WriterBusy(AlertSpineError):
    """Raised when another canonical writer already owns the OS lock."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _event_stream_hash(events: list[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(_canonical_bytes(event))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _validate_producer_id(value: object) -> str:
    producer_id = str(value or "").strip().lower()
    if not _PRODUCER_RE.fullmatch(producer_id):
        raise AlertValidationError("PRODUCER_ID_INVALID")
    return producer_id


def _validate_producer_epoch(value: object) -> str:
    producer_epoch = str(value or "").strip()
    if not _EPOCH_RE.fullmatch(producer_epoch):
        raise AlertValidationError("PRODUCER_EPOCH_INVALID")
    return producer_epoch


def _bounded_strings(
    value: object,
    *,
    field: str,
    uppercase: bool = False,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_ENTITY_COUNT:
        raise AlertValidationError(f"{field.upper()}_INVALID")
    normalized: list[str] = []
    for raw in value:
        item = str(raw or "").strip()
        if uppercase:
            item = item.upper()
        if not item or len(item) > 128:
            raise AlertValidationError(f"{field.upper()}_INVALID")
        normalized.append(item)
    return sorted(set(normalized))


def _event_reference(value: object, *, field: str) -> str | None:
    if value in (None, ""):
        return None
    reference = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(reference):
        raise AlertValidationError(f"{field.upper()}_INVALID")
    return reference


def _score_components(value: object) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 128:
        raise AlertValidationError("DETERMINISTIC_SCORE_COMPONENTS_INVALID")
    supplied: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if key not in SCORE_WEIGHTS_BPS:
            raise AlertValidationError("DETERMINISTIC_SCORE_COMPONENTS_INVALID")
        try:
            number = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "DETERMINISTIC_SCORE_COMPONENTS_INVALID"
            ) from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise AlertValidationError("DETERMINISTIC_SCORE_COMPONENTS_INVALID")
        supplied[key] = number
    return {key: supplied.get(key, 0.0) for key in SCORE_WEIGHTS_BPS}


def _score_receipt(components: Mapping[str, float]) -> dict[str, Any]:
    contributions = {
        key: int(round(float(components[key]) * weight))
        for key, weight in SCORE_WEIGHTS_BPS.items()
    }
    total_bps = sum(contributions.values())
    return {
        "schema_version": SCORE_POLICY_VERSION,
        "policy_hash": _sha256(
            {
                "version": SCORE_POLICY_VERSION,
                "weights_bps": SCORE_WEIGHTS_BPS,
                "missing_component_value": 0.0,
            }
        ),
        "weights_bps": dict(SCORE_WEIGHTS_BPS),
        "contributions_bps": contributions,
        "score_bps": total_bps,
        "score": round(total_bps / 10_000.0, 6),
        "score_semantics": "RANKING_SCORE_NOT_PROBABILITY",
        "ablations": {
            key: {
                "removed_contribution_bps": contribution,
                "score_without_component_bps": total_bps - contribution,
            }
            for key, contribution in contributions.items()
        },
        "model_inputs_used": False,
    }


def _reject_order_capability(value: object, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if key in _FORBIDDEN_ORDER_KEYS:
                raise AlertValidationError(f"ORDER_CAPABILITY_FORBIDDEN:{path}.{key}")
            _reject_order_capability(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_order_capability(child, path=f"{path}[{index}]")


def _evidence_refs(
    value: object,
    *,
    source_id: str,
    source_uri: str,
    source_hash: str,
) -> list[dict[str, str]]:
    if value is None:
        value = [
            {
                "evidence_id": source_id,
                "source_uri": source_uri,
                "content_hash": source_hash,
            }
        ]
    if not isinstance(value, (list, tuple)) or not value or len(value) > _MAX_EVIDENCE_REFS:
        raise AlertValidationError("EVIDENCE_REFS_INVALID")
    normalized: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise AlertValidationError("EVIDENCE_REFS_INVALID")
        evidence_id = str(raw.get("evidence_id") or "").strip()
        evidence_uri = str(raw.get("source_uri") or "").strip()
        content_hash = str(raw.get("content_hash") or "").strip().lower()
        if (
            not evidence_id
            or not evidence_uri
            or not _SHA256_RE.fullmatch(content_hash)
        ):
            raise AlertValidationError("EVIDENCE_REFS_INVALID")
        normalized.append(
            {
                "evidence_id": evidence_id,
                "source_uri": evidence_uri,
                "content_hash": content_hash,
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            item["evidence_id"],
            item["source_uri"],
            item["content_hash"],
        ),
    )


def _validate_proposal(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AlertValidationError("PROPOSAL_NOT_MAPPING")
    proposal = dict(payload)
    if proposal.get("schema_version") != PROPOSAL_SCHEMA:
        raise AlertValidationError("PROPOSAL_SCHEMA_INVALID")
    producer_id = _validate_producer_id(proposal.get("producer_id"))
    producer_epoch = _validate_producer_epoch(proposal.get("producer_epoch"))
    try:
        producer_seq = int(proposal.get("producer_seq"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AlertValidationError("PRODUCER_SEQ_INVALID") from exc
    if producer_seq < 0:
        raise AlertValidationError("PRODUCER_SEQ_INVALID")
    source = proposal.get("source_receipt")
    if not isinstance(source, Mapping):
        raise AlertValidationError("SOURCE_RECEIPT_MISSING")
    source_id = str(source.get("source_id") or "").strip()
    source_uri = str(source.get("source_uri") or "").strip()
    source_hash = str(source.get("source_content_hash") or "").strip().lower()
    if not source_id or not source_uri or not _SHA256_RE.fullmatch(source_hash):
        raise AlertValidationError("SOURCE_RECEIPT_INVALID")
    source_receipt = {
        "source_id": source_id,
        "source_uri": source_uri,
        "source_content_hash": source_hash,
    }
    source_event_id_raw = proposal.get("source_event_id")
    source_event_id = (
        str(source_event_id_raw).strip() if source_event_id_raw is not None else None
    )
    if source_event_id == "":
        source_event_id = None
    if source_event_id is not None and len(source_event_id) > 256:
        raise AlertValidationError("SOURCE_EVENT_ID_INVALID")
    timestamps: list[int] = []
    for field in ("observed_at_ms", "fetched_at_ms", "verified_at_ms"):
        try:
            value = int(proposal.get(field))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(f"TIMESTAMP_INVALID:{field}") from exc
        if value < 0:
            raise AlertValidationError(f"TIMESTAMP_INVALID:{field}")
        timestamps.append(value)
    if timestamps != sorted(timestamps):
        raise AlertValidationError("TIMESTAMP_ORDER_INVALID")
    parsed_at_raw = proposal.get("parsed_at_ms")
    try:
        parsed_at_ms = (
            timestamps[1] if parsed_at_raw is None else int(parsed_at_raw)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise AlertValidationError("TIMESTAMP_INVALID:parsed_at_ms") from exc
    if not timestamps[1] <= parsed_at_ms <= timestamps[2]:
        raise AlertValidationError("PARSED_TIMESTAMP_ORDER_INVALID")
    declared_parsed_origin = str(proposal.get("parsed_at_origin") or "").strip().upper()
    if parsed_at_raw is None:
        parsed_at_origin = "FETCHED_AT_FALLBACK"
    elif declared_parsed_origin:
        if declared_parsed_origin not in {"FETCHED_AT_FALLBACK", "SOURCE_ADAPTER"}:
            raise AlertValidationError("PARSED_AT_ORIGIN_INVALID")
        if declared_parsed_origin == "FETCHED_AT_FALLBACK" and parsed_at_ms != timestamps[1]:
            raise AlertValidationError("PARSED_AT_FALLBACK_MISMATCH")
        parsed_at_origin = declared_parsed_origin
    else:
        parsed_at_origin = "SOURCE_ADAPTER"
    source_event_time_raw = proposal.get("source_event_time_ms")
    source_event_time_ms: int | None = None
    if source_event_time_raw is not None:
        try:
            source_event_time_ms = int(source_event_time_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError("TIMESTAMP_INVALID:source_event_time_ms") from exc
        if source_event_time_ms < 0 or source_event_time_ms > timestamps[0]:
            raise AlertValidationError("SOURCE_EVENT_TIME_IMPOSSIBLE")
    source_publish_raw = proposal.get("source_publish_time_ms")
    source_publish_time_ms: int | None = None
    if source_publish_raw is not None:
        try:
            source_publish_time_ms = int(source_publish_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "TIMESTAMP_INVALID:source_publish_time_ms"
            ) from exc
        if source_publish_time_ms < 0 or source_publish_time_ms > timestamps[0]:
            raise AlertValidationError("SOURCE_PUBLISH_TIME_IMPOSSIBLE")
        if (
            source_event_time_ms is not None
            and source_publish_time_ms < source_event_time_ms
        ):
            raise AlertValidationError("SOURCE_PUBLISH_BEFORE_EVENT")
    source_available_raw = proposal.get("source_available_time_ms")
    try:
        source_available_time_ms = (
            timestamps[0]
            if source_available_raw is None
            else int(source_available_raw)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise AlertValidationError(
            "TIMESTAMP_INVALID:source_available_time_ms"
        ) from exc
    if source_available_time_ms < 0 or source_available_time_ms > timestamps[0]:
        raise AlertValidationError("SOURCE_AVAILABLE_TIME_IMPOSSIBLE")
    if (
        source_publish_time_ms is not None
        and source_available_time_ms < source_publish_time_ms
    ):
        raise AlertValidationError("SOURCE_AVAILABLE_BEFORE_PUBLISH")
    declared_available_origin = str(
        proposal.get("source_available_time_origin") or ""
    ).strip().upper()
    if source_available_raw is None:
        source_available_origin = "OBSERVED_AT_FALLBACK"
    elif declared_available_origin:
        if declared_available_origin not in {
            "OBSERVED_AT_FALLBACK",
            "SOURCE_ADAPTER",
        }:
            raise AlertValidationError("SOURCE_AVAILABLE_ORIGIN_INVALID")
        if (
            declared_available_origin == "OBSERVED_AT_FALLBACK"
            and source_available_time_ms != timestamps[0]
        ):
            raise AlertValidationError("SOURCE_AVAILABLE_FALLBACK_MISMATCH")
        source_available_origin = declared_available_origin
    else:
        source_available_origin = "SOURCE_ADAPTER"
    expires_at_raw = proposal.get("expires_at_ms")
    expires_at_ms: int | None = None
    if expires_at_raw is not None:
        try:
            expires_at_ms = int(expires_at_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError("TIMESTAMP_INVALID:expires_at_ms") from exc
        if expires_at_ms < timestamps[2]:
            raise AlertValidationError("EXPIRES_AT_IMPOSSIBLE")
    category = str(proposal.get("category") or "").strip().upper()
    headline = str(proposal.get("headline") or "").strip()
    dedup_key = str(proposal.get("dedup_key") or "").strip()
    if not category or not headline or len(headline) > _MAX_HEADLINE:
        raise AlertValidationError("ALERT_CONTENT_INVALID")
    if proposal.get("paper_read_only") is not True or proposal.get("real_execution") is not False:
        raise AlertValidationError("PAPER_READ_ONLY_REQUIRED")
    if not isinstance(proposal.get("payload", {}), Mapping):
        raise AlertValidationError("PAYLOAD_NOT_MAPPING")
    normalized_payload = dict(proposal.get("payload") or {})
    _reject_order_capability(normalized_payload)
    payload_hash = _sha256(normalized_payload)
    supplied_payload_hash = proposal.get("payload_hash")
    if supplied_payload_hash is not None and (
        str(supplied_payload_hash).strip().lower() != payload_hash
    ):
        raise AlertValidationError("PAYLOAD_HASH_MISMATCH")
    entity_ids = _bounded_strings(proposal.get("entity_ids"), field="entity_ids")
    normalized_tickers = _bounded_strings(
        proposal.get("normalized_tickers"),
        field="normalized_tickers",
        uppercase=True,
    )
    source_event_dedup = (
        "source-event:"
        + _sha256({"source_id": source_id, "source_event_id": source_event_id})
        if source_event_id is not None
        else None
    )
    fallback_dedup = "fallback:" + _sha256(
        {
            "source_id": source_id,
            "source_uri": source_uri,
            "source_content_hash": source_hash,
            "category": category,
            "entity_ids": entity_ids,
            "normalized_tickers": normalized_tickers,
            "headline": headline,
        }
    )
    declared_origin = str(proposal.get("dedup_key_origin") or "").strip().upper()
    if dedup_key:
        dedup_key_origin = declared_origin or "PROVIDED"
        if dedup_key_origin == "SOURCE_EVENT_ID" and dedup_key != source_event_dedup:
            raise AlertValidationError("SOURCE_EVENT_DEDUP_MISMATCH")
        if dedup_key_origin == "CANONICAL_FALLBACK" and dedup_key != fallback_dedup:
            raise AlertValidationError("FALLBACK_DEDUP_MISMATCH")
        if dedup_key_origin not in {
            "PROVIDED",
            "SOURCE_EVENT_ID",
            "CANONICAL_FALLBACK",
        }:
            raise AlertValidationError("DEDUP_KEY_ORIGIN_INVALID")
    elif source_event_dedup is not None:
        dedup_key = source_event_dedup
        dedup_key_origin = "SOURCE_EVENT_ID"
    else:
        dedup_key = fallback_dedup
        dedup_key_origin = "CANONICAL_FALLBACK"
    if len(dedup_key) > _MAX_DEDUP_KEY:
        raise AlertValidationError("DEDUP_KEY_INVALID")
    evidence_refs = _evidence_refs(
        proposal.get("evidence_refs"),
        source_id=source_id,
        source_uri=source_uri,
        source_hash=source_hash,
    )
    source_health_state = str(
        proposal.get("source_health_state") or "COVERAGE_UNKNOWN"
    ).strip().upper()
    freshness_state = str(proposal.get("freshness_state") or "UNKNOWN").strip().upper()
    if source_health_state not in SOURCE_HEALTH_STATES:
        raise AlertValidationError("SOURCE_HEALTH_STATE_INVALID")
    if freshness_state not in FRESHNESS_STATES:
        raise AlertValidationError("FRESHNESS_STATE_INVALID")
    if category == "NO_NEWS" and (
        source_health_state != "HEALTHY" or freshness_state != "FRESH"
    ):
        raise AlertValidationError("NO_NEWS_REQUIRES_HEALTHY_FRESH_SOURCE")
    components = _score_components(proposal.get("deterministic_score_components"))
    score_receipt = _score_receipt(components)
    model_opinion_raw = proposal.get("model_opinion")
    if model_opinion_raw is not None and not isinstance(model_opinion_raw, Mapping):
        raise AlertValidationError("MODEL_OPINION_INVALID")
    model_opinion = (
        {**dict(model_opinion_raw), "authoritative": False}
        if isinstance(model_opinion_raw, Mapping)
        else None
    )
    policy_version = str(proposal.get("policy_version") or "").strip()
    ingestion_code_sha = str(proposal.get("ingestion_code_sha") or "").strip().lower()
    if not policy_version or len(policy_version) > 128:
        raise AlertValidationError("POLICY_VERSION_INVALID")
    if not _CODE_SHA_RE.fullmatch(ingestion_code_sha):
        raise AlertValidationError("INGESTION_CODE_SHA_INVALID")
    revision_of = _event_reference(proposal.get("revision_of"), field="revision_of")
    retracts = _event_reference(proposal.get("retracts"), field="retracts")
    if revision_of is not None and retracts is not None:
        raise AlertValidationError("REVISION_AND_RETRACTION_MUTUALLY_EXCLUSIVE")
    proposal.update(
        {
            "producer_id": producer_id,
            "producer_epoch": producer_epoch,
            "producer_seq": producer_seq,
            "source_receipt": source_receipt,
            "source_receipt_hash": _sha256(source_receipt),
            "source_event_id": source_event_id,
            "source_event_time_ms": source_event_time_ms,
            "source_publish_time_ms": source_publish_time_ms,
            "source_available_time_ms": source_available_time_ms,
            "source_available_time_origin": source_available_origin,
            "observed_at_ms": timestamps[0],
            "fetched_at_ms": timestamps[1],
            "parsed_at_ms": parsed_at_ms,
            "parsed_at_origin": parsed_at_origin,
            "verified_at_ms": timestamps[2],
            "expires_at_ms": expires_at_ms,
            "category": category,
            "headline": headline,
            "dedup_key": dedup_key,
            "dedup_key_origin": dedup_key_origin,
            "entity_ids": entity_ids,
            "normalized_tickers": normalized_tickers,
            "evidence_refs": evidence_refs,
            "source_health_state": source_health_state,
            "freshness_state": freshness_state,
            "deterministic_score_components": components,
            "deterministic_score": score_receipt["score"],
            "deterministic_score_receipt": score_receipt,
            "model_opinion": model_opinion,
            "economic_admission_state": "NOT_EVALUATED",
            "order_intent_allowed": False,
            "policy_version": policy_version,
            "ingestion_code_sha": ingestion_code_sha,
            "revision_of": revision_of,
            "retracts": retracts,
            "payload": normalized_payload,
            "payload_hash": payload_hash,
            "paper_read_only": True,
            "real_execution": False,
        }
    )
    body = {key: value for key, value in proposal.items() if key != "proposal_id"}
    expected_id = _sha256(body)
    supplied_id = str(proposal.get("proposal_id") or expected_id)
    if supplied_id != expected_id:
        raise AlertValidationError("PROPOSAL_ID_MISMATCH")
    proposal["proposal_id"] = expected_id
    return proposal


def build_alert_proposal(
    *,
    producer_id: str,
    producer_epoch: str,
    producer_seq: int,
    source_id: str,
    source_uri: str,
    source_content_hash: str,
    observed_at_ms: int,
    fetched_at_ms: int,
    verified_at_ms: int,
    category: str,
    headline: str,
    dedup_key: str | None,
    policy_version: str,
    ingestion_code_sha: str,
    source_event_id: str | None = None,
    source_event_time_ms: int | None = None,
    source_publish_time_ms: int | None = None,
    source_available_time_ms: int | None = None,
    parsed_at_ms: int | None = None,
    expires_at_ms: int | None = None,
    entity_ids: list[str] | tuple[str, ...] | None = None,
    normalized_tickers: list[str] | tuple[str, ...] | None = None,
    evidence_refs: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    source_health_state: str = "COVERAGE_UNKNOWN",
    freshness_state: str = "UNKNOWN",
    deterministic_score_components: Mapping[str, float] | None = None,
    model_opinion: Mapping[str, Any] | None = None,
    revision_of: str | None = None,
    retracts: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a paper/read-only producer proposal."""

    return _validate_proposal(
        {
            "schema_version": PROPOSAL_SCHEMA,
            "producer_id": producer_id,
            "producer_epoch": producer_epoch,
            "producer_seq": producer_seq,
            "source_receipt": {
                "source_id": source_id,
                "source_uri": source_uri,
                "source_content_hash": source_content_hash,
            },
            "source_event_id": source_event_id,
            "source_event_time_ms": source_event_time_ms,
            "source_publish_time_ms": source_publish_time_ms,
            "source_available_time_ms": source_available_time_ms,
            "observed_at_ms": observed_at_ms,
            "fetched_at_ms": fetched_at_ms,
            "parsed_at_ms": parsed_at_ms,
            "verified_at_ms": verified_at_ms,
            "expires_at_ms": expires_at_ms,
            "category": category,
            "headline": headline,
            "dedup_key": dedup_key,
            "entity_ids": list(entity_ids or []),
            "normalized_tickers": list(normalized_tickers or []),
            "evidence_refs": list(evidence_refs) if evidence_refs is not None else None,
            "source_health_state": source_health_state,
            "freshness_state": freshness_state,
            "deterministic_score_components": dict(
                deterministic_score_components or {}
            ),
            "model_opinion": dict(model_opinion) if model_opinion is not None else None,
            "policy_version": policy_version,
            "ingestion_code_sha": ingestion_code_sha,
            "revision_of": revision_of,
            "retracts": retracts,
            "payload": dict(payload or {}),
            "paper_read_only": True,
            "real_execution": False,
        }
    )


def _event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "source_id": event.get("source_id"),
        "revision_of": event.get("revision_of"),
        "retracts": event.get("retracts"),
    }
    if event.get("source_event_id") is not None:
        identity["source_event_id"] = event.get("source_event_id")
    else:
        identity["dedup_key"] = event.get("dedup_key")
        identity["source_content_hash"] = event.get("source_content_hash")
    return identity


def _validate_lifecycle_receipt(event: Mapping[str, Any]) -> None:
    receipt = event.get("lifecycle_receipt")
    if not isinstance(receipt, list) or len(receipt) != len(
        IMMUTABLE_LIFECYCLE_STATES
    ):
        raise AlertValidationError("LIFECYCLE_RECEIPT_INVALID")
    expected_times = (
        event.get("observed_at_ms"),
        event.get("fetched_at_ms"),
        event.get("verified_at_ms"),
        event.get("admitted_at_ms"),
    )
    normalized: list[tuple[str, int]] = []
    for item in receipt:
        if not isinstance(item, Mapping):
            raise AlertValidationError("LIFECYCLE_RECEIPT_INVALID")
        try:
            at_ms = int(item.get("at_ms"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError("LIFECYCLE_RECEIPT_INVALID") from exc
        normalized.append((str(item.get("state") or ""), at_ms))
    if tuple(state for state, _ in normalized) != IMMUTABLE_LIFECYCLE_STATES:
        raise AlertValidationError("LIFECYCLE_TRANSITION_INVALID")
    if tuple(at_ms for _, at_ms in normalized) != expected_times:
        raise AlertValidationError("LIFECYCLE_TIMESTAMP_MISMATCH")
    if event.get("lifecycle_state") != "ADMITTED":
        raise AlertValidationError("IMMUTABLE_LIFECYCLE_STATE_INVALID")


def _validate_canonical_event(
    payload: object,
    *,
    expected_sequence: int | None = None,
    prior_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AlertValidationError("CANONICAL_EVENT_NOT_MAPPING")
    event = dict(payload)
    if event.get("schema_version") != EVENT_SCHEMA:
        raise AlertValidationError("CANONICAL_EVENT_SCHEMA_INVALID")
    event_id = str(event.get("event_id") or "").strip().lower()
    proposal_id = str(event.get("proposal_id") or "").strip().lower()
    if not _SHA256_RE.fullmatch(event_id) or not _SHA256_RE.fullmatch(proposal_id):
        raise AlertValidationError("CANONICAL_EVENT_ID_INVALID")
    producer_id = _validate_producer_id(event.get("producer_id"))
    producer_epoch = _validate_producer_epoch(event.get("producer_epoch"))
    try:
        producer_seq = int(event.get("producer_seq"))
        ledger_sequence = int(event.get("ledger_sequence"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AlertValidationError("CANONICAL_SEQUENCE_INVALID") from exc
    if producer_seq < 0 or ledger_sequence < 1:
        raise AlertValidationError("CANONICAL_SEQUENCE_INVALID")
    if expected_sequence is not None and ledger_sequence != expected_sequence:
        raise AlertValidationError("CANONICAL_LEDGER_SEQUENCE_INVALID")

    source = event.get("source_receipt")
    if not isinstance(source, Mapping):
        raise AlertValidationError("CANONICAL_SOURCE_RECEIPT_MISSING")
    source_id = str(source.get("source_id") or "").strip()
    source_uri = str(source.get("source_uri") or "").strip()
    source_hash = str(source.get("source_content_hash") or "").strip().lower()
    normalized_source = {
        "source_id": source_id,
        "source_uri": source_uri,
        "source_content_hash": source_hash,
    }
    if (
        not source_id
        or not source_uri
        or not _SHA256_RE.fullmatch(source_hash)
        or event.get("source_id") != source_id
        or event.get("source_uri") != source_uri
        or event.get("source_content_hash") != source_hash
        or event.get("source_receipt_hash") != _sha256(normalized_source)
    ):
        raise AlertValidationError("CANONICAL_SOURCE_RECEIPT_INVALID")
    source_event_id_raw = event.get("source_event_id")
    source_event_id = (
        str(source_event_id_raw).strip() if source_event_id_raw is not None else None
    )
    if source_event_id == "":
        source_event_id = None
    if source_event_id is not None and len(source_event_id) > 256:
        raise AlertValidationError("CANONICAL_SOURCE_EVENT_ID_INVALID")

    times: list[int] = []
    for field in (
        "observed_at_ms",
        "fetched_at_ms",
        "parsed_at_ms",
        "verified_at_ms",
        "admitted_at_ms",
    ):
        try:
            at_ms = int(event.get(field))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(f"CANONICAL_TIMESTAMP_INVALID:{field}") from exc
        if at_ms < 0:
            raise AlertValidationError(f"CANONICAL_TIMESTAMP_INVALID:{field}")
        times.append(at_ms)
    if times != sorted(times):
        raise AlertValidationError("CANONICAL_TIMESTAMP_ORDER_INVALID")
    if event.get("parsed_at_origin") not in {
        "FETCHED_AT_FALLBACK",
        "SOURCE_ADAPTER",
    }:
        raise AlertValidationError("CANONICAL_PARSED_AT_ORIGIN_INVALID")
    if event.get("parsed_at_origin") == "FETCHED_AT_FALLBACK" and times[2] != times[1]:
        raise AlertValidationError("CANONICAL_PARSED_AT_FALLBACK_MISMATCH")
    source_event_time = event.get("source_event_time_ms")
    if source_event_time is not None:
        try:
            source_event_time = int(source_event_time)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "CANONICAL_TIMESTAMP_INVALID:source_event_time_ms"
            ) from exc
        if source_event_time < 0 or source_event_time > times[0]:
            raise AlertValidationError("CANONICAL_SOURCE_EVENT_TIME_IMPOSSIBLE")
    source_publish_time = event.get("source_publish_time_ms")
    if source_publish_time is not None:
        try:
            source_publish_time = int(source_publish_time)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "CANONICAL_TIMESTAMP_INVALID:source_publish_time_ms"
            ) from exc
        if source_publish_time < 0 or source_publish_time > times[0]:
            raise AlertValidationError("CANONICAL_SOURCE_PUBLISH_TIME_IMPOSSIBLE")
        if source_event_time is not None and source_publish_time < source_event_time:
            raise AlertValidationError("CANONICAL_SOURCE_PUBLISH_BEFORE_EVENT")
    try:
        source_available_time = int(event.get("source_available_time_ms"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AlertValidationError(
            "CANONICAL_TIMESTAMP_INVALID:source_available_time_ms"
        ) from exc
    if source_available_time < 0 or source_available_time > times[0]:
        raise AlertValidationError("CANONICAL_SOURCE_AVAILABLE_TIME_IMPOSSIBLE")
    if source_publish_time is not None and source_available_time < source_publish_time:
        raise AlertValidationError("CANONICAL_SOURCE_AVAILABLE_BEFORE_PUBLISH")
    if event.get("source_available_time_origin") not in {
        "OBSERVED_AT_FALLBACK",
        "SOURCE_ADAPTER",
    }:
        raise AlertValidationError("CANONICAL_SOURCE_AVAILABLE_ORIGIN_INVALID")
    if (
        event.get("source_available_time_origin") == "OBSERVED_AT_FALLBACK"
        and source_available_time != times[0]
    ):
        raise AlertValidationError("CANONICAL_SOURCE_AVAILABLE_FALLBACK_MISMATCH")
    expected_availability_lag = times[0] - source_available_time
    if event.get("source_available_at_ms") != source_available_time:
        raise AlertValidationError("CANONICAL_SOURCE_AVAILABILITY_ALIAS_INVALID")
    if event.get("availability_lag_ms") != expected_availability_lag:
        raise AlertValidationError("CANONICAL_AVAILABILITY_LAG_INVALID")
    expires_at = event.get("expires_at_ms")
    if expires_at is not None:
        try:
            expires_at = int(expires_at)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "CANONICAL_TIMESTAMP_INVALID:expires_at_ms"
            ) from exc
        if expires_at < times[4]:
            raise AlertValidationError("CANONICAL_EXPIRES_AT_IMPOSSIBLE")

    category = str(event.get("category") or "").strip().upper()
    headline = str(event.get("headline") or "").strip()
    dedup_key = str(event.get("dedup_key") or "").strip()
    if not category or not headline or len(headline) > _MAX_HEADLINE:
        raise AlertValidationError("CANONICAL_ALERT_CONTENT_INVALID")
    if not dedup_key or len(dedup_key) > _MAX_DEDUP_KEY:
        raise AlertValidationError("CANONICAL_DEDUP_KEY_INVALID")
    if event.get("dedup_key_origin") not in {
        "PROVIDED",
        "SOURCE_EVENT_ID",
        "CANONICAL_FALLBACK",
    }:
        raise AlertValidationError("CANONICAL_DEDUP_ORIGIN_INVALID")
    if event.get("entity_ids") != _bounded_strings(
        event.get("entity_ids"), field="entity_ids"
    ):
        raise AlertValidationError("CANONICAL_ENTITY_IDS_NOT_NORMALIZED")
    if event.get("normalized_tickers") != _bounded_strings(
        event.get("normalized_tickers"),
        field="normalized_tickers",
        uppercase=True,
    ):
        raise AlertValidationError("CANONICAL_TICKERS_NOT_NORMALIZED")
    if event.get("evidence_refs") != _evidence_refs(
        event.get("evidence_refs"),
        source_id=source_id,
        source_uri=source_uri,
        source_hash=source_hash,
    ):
        raise AlertValidationError("CANONICAL_EVIDENCE_REFS_NOT_NORMALIZED")
    source_health_state = str(event.get("source_health_state") or "").upper()
    freshness_state = str(event.get("freshness_state") or "").upper()
    if source_health_state not in SOURCE_HEALTH_STATES:
        raise AlertValidationError("CANONICAL_SOURCE_HEALTH_INVALID")
    if freshness_state not in FRESHNESS_STATES:
        raise AlertValidationError("CANONICAL_FRESHNESS_INVALID")
    canonical_components = _score_components(
        event.get("deterministic_score_components")
    )
    if event.get("deterministic_score_components") != canonical_components:
        raise AlertValidationError("CANONICAL_SCORE_COMPONENTS_NOT_NORMALIZED")
    score_receipt = _score_receipt(canonical_components)
    if (
        event.get("deterministic_score") != score_receipt["score"]
        or event.get("deterministic_score_receipt") != score_receipt
    ):
        raise AlertValidationError("CANONICAL_SCORE_RECEIPT_INVALID")
    model_opinion = event.get("model_opinion")
    if model_opinion is not None and (
        not isinstance(model_opinion, Mapping)
        or model_opinion.get("authoritative") is not False
    ):
        raise AlertValidationError("CANONICAL_MODEL_OPINION_INVALID")
    policy_version = str(event.get("policy_version") or "").strip()
    ingestion_code_sha = str(event.get("ingestion_code_sha") or "").strip().lower()
    if not policy_version or len(policy_version) > 128:
        raise AlertValidationError("CANONICAL_POLICY_VERSION_INVALID")
    if not _CODE_SHA_RE.fullmatch(ingestion_code_sha):
        raise AlertValidationError("CANONICAL_INGESTION_CODE_SHA_INVALID")
    revision_of = _event_reference(event.get("revision_of"), field="revision_of")
    retracts = _event_reference(event.get("retracts"), field="retracts")
    if revision_of is not None and retracts is not None:
        raise AlertValidationError("CANONICAL_REVISION_RETRACTION_CONFLICT")
    if not isinstance(event.get("payload"), Mapping):
        raise AlertValidationError("CANONICAL_PAYLOAD_INVALID")
    normalized_payload = dict(event["payload"])
    _reject_order_capability(normalized_payload)
    payload_hash = str(event.get("payload_hash") or "").strip().lower()
    if (
        not _SHA256_RE.fullmatch(payload_hash)
        or event.get("payload_hash") != payload_hash
        or payload_hash != _sha256(normalized_payload)
    ):
        raise AlertValidationError("CANONICAL_PAYLOAD_HASH_INVALID")
    if (
        event.get("economic_admission_state") != "NOT_EVALUATED"
        or event.get("order_intent_allowed") is not False
    ):
        raise AlertValidationError("CANONICAL_ECONOMIC_AUTHORITY_FORBIDDEN")
    if event.get("paper_read_only") is not True or event.get("real_execution") is not False:
        raise AlertValidationError("CANONICAL_PAPER_READ_ONLY_REQUIRED")
    if "displayed_at_ms" in event or "projected_at_ms" in event:
        raise AlertValidationError("PROJECTION_TELEMETRY_IN_IMMUTABLE_EVENT")
    if event_id != _sha256(_event_identity(event)):
        raise AlertValidationError("CANONICAL_EVENT_ID_MISMATCH")
    _validate_lifecycle_receipt(event)

    if prior_by_id is not None:
        existing = prior_by_id.get(event_id)
        same_epoch = [
            previous
            for previous in prior_by_id.values()
            if previous.get("producer_id") == producer_id
            and previous.get("producer_epoch") == producer_epoch
        ]
        expected_producer_seq = (
            max(int(previous["producer_seq"]) for previous in same_epoch) + 1
            if same_epoch
            else 0
        )
        if existing is None and producer_seq < expected_producer_seq:
            raise AlertValidationError("PRODUCER_SEQUENCE_OUT_OF_ORDER")
        stored_expected = int(event.get("producer_expected_seq", -1))
        expected_for_event = (
            int(existing.get("producer_expected_seq", stored_expected))
            if existing is not None
            else expected_producer_seq
        )
        expected_gap = (
            int(existing.get("producer_gap_size", 0))
            if existing is not None
            else max(0, producer_seq - expected_for_event)
        )
        if (
            stored_expected != expected_for_event
            or event.get("producer_gap_detected") is not (expected_gap > 0)
            or event.get("producer_gap_size") != expected_gap
        ):
            raise AlertValidationError("PRODUCER_SEQUENCE_GAP_RECEIPT_INVALID")
        for field, reference in (("revision_of", revision_of), ("retracts", retracts)):
            if reference is not None and reference not in prior_by_id:
                raise AlertValidationError(f"{field.upper()}_TARGET_UNKNOWN")
        retracted = {
            str(previous.get("retracts"))
            for previous in prior_by_id.values()
            if previous.get("retracts")
        }
        if revision_of in retracted:
            raise AlertValidationError("REVISION_TARGET_ALREADY_RETRACTED")
        if retracts in retracted:
            raise AlertValidationError("RETRACTION_TARGET_ALREADY_RETRACTED")

    event.update(
        {
            "event_id": event_id,
            "producer_id": producer_id,
            "producer_epoch": producer_epoch,
            "producer_seq": producer_seq,
            "ledger_sequence": ledger_sequence,
            "source_event_time_ms": source_event_time,
            "source_publish_time_ms": source_publish_time,
            "source_available_time_ms": source_available_time,
            "source_event_id": source_event_id,
            "expires_at_ms": expires_at,
            "revision_of": revision_of,
            "retracts": retracts,
        }
    )
    return event


def jsonl_append_fsync(path: str | Path, event: Mapping[str, Any]) -> None:
    """Reuse the repository append+flush+fsync primitive for one event."""

    if append_jsonl(path, [dict(event)], fsync=True) != 1:
        raise AlertSpineError("CANONICAL_APPEND_FAILED")


class SingleWriterFileLock:
    """Cross-platform advisory lock released automatically after a process kill."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: Any | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise WriterBusy("CANONICAL_WRITER_ALREADY_ACTIVE") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> SingleWriterFileLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class AlertSpinePaths:
    root: Path
    pending_root: Path
    inflight_root: Path
    acknowledged_root: Path
    ledger_path: Path
    ledger_segments_root: Path
    ledger_latest_pointer_path: Path
    projection_path: Path
    writer_lock_path: Path
    writer_cursor_path: Path
    projection_cursor_path: Path
    duplicate_observations_path: Path

    @classmethod
    def from_root(cls, root: str | Path) -> AlertSpinePaths:
        base = Path(root).resolve()
        paths = cls(
            root=base,
            pending_root=base / "producer_inboxes" / "pending",
            inflight_root=base / "writer_state" / "inflight",
            acknowledged_root=base / "producer_inboxes" / "acknowledged",
            ledger_path=base / "canonical" / "alerts.jsonl",
            ledger_segments_root=base / "canonical" / "segments",
            ledger_latest_pointer_path=base / "canonical" / "alerts.latest.json",
            projection_path=base / "projections" / "alerts_dashboard.json",
            writer_lock_path=base / "writer_state" / "canonical_writer.lock",
            writer_cursor_path=base / "writer_state" / "canonical_cursor.json",
            projection_cursor_path=base / "projections" / "canonical_cursor.json",
            duplicate_observations_path=(
                base / "diagnostics" / "duplicate_observations.jsonl"
            ),
        )
        if _is_within(paths.ledger_path, paths.pending_root):
            raise AlertSpineError("CANONICAL_LEDGER_INSIDE_PRODUCER_INBOX")
        if _is_within(paths.projection_path, paths.pending_root):
            raise AlertSpineError("PROJECTION_INSIDE_PRODUCER_INBOX")
        return paths


@dataclass(frozen=True, slots=True)
class AlertProducerInbox:
    """Write-only producer capability scoped to one isolated pending directory."""

    pending_root: Path
    producer_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "pending_root", Path(self.pending_root).resolve())
        object.__setattr__(self, "producer_id", _validate_producer_id(self.producer_id))

    @property
    def directory(self) -> Path:
        return self.pending_root / self.producer_id

    def submit(self, proposal: Mapping[str, Any]) -> Path:
        validated = _validate_proposal(proposal)
        if validated["producer_id"] != self.producer_id:
            raise AlertValidationError("PRODUCER_CAPABILITY_MISMATCH")
        self.directory.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{int(validated['producer_seq']):020d}-"
            f"{validated['proposal_id']}.json"
        )
        target = (self.directory / filename).resolve()
        if not _is_within(target, self.directory):
            raise AlertValidationError("PRODUCER_PATH_ESCAPE")
        encoded = _canonical_bytes(validated) + b"\n"
        temporary_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(temporary_descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                if target.read_bytes() != encoded:
                    raise AlertValidationError("PROPOSAL_PATH_COLLISION") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return target


class CanonicalAlertWriter:
    """The only authority allowed to append and project canonical alerts."""

    def __init__(
        self,
        paths: AlertSpinePaths,
        *,
        clock_ms: Callable[[], int] | None = None,
        ledger_rotate_bytes: int = _DEFAULT_LEDGER_ROTATE_BYTES,
    ) -> None:
        self.paths = paths
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.ledger_rotate_bytes = max(1, int(ledger_rotate_bytes))

    def producer(self, producer_id: str) -> AlertProducerInbox:
        return AlertProducerInbox(self.paths.pending_root, producer_id)

    def _cursor_payload(
        self,
        *,
        consumer: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema_version": "hypersmart.alert_cursor.v1",
            "consumer": consumer,
            "ledger_sequence": len(events),
            "event_id": events[-1]["event_id"] if events else None,
            "ledger_prefix_hash": _event_stream_hash(events),
            "paper_read_only": True,
            "real_execution": False,
        }

    def _validate_cursor(
        self,
        path: Path,
        *,
        consumer: str,
        events: list[dict[str, Any]],
    ) -> int:
        if not path.is_file():
            return 0
        try:
            cursor = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalLedgerCorruption("DURABLE_CURSOR_INVALID") from exc
        if (
            not isinstance(cursor, Mapping)
            or cursor.get("schema_version") != "hypersmart.alert_cursor.v1"
            or cursor.get("consumer") != consumer
            or cursor.get("paper_read_only") is not True
            or cursor.get("real_execution") is not False
        ):
            raise CanonicalLedgerCorruption("DURABLE_CURSOR_SCHEMA_INVALID")
        try:
            sequence = int(cursor.get("ledger_sequence"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise CanonicalLedgerCorruption("DURABLE_CURSOR_SEQUENCE_INVALID") from exc
        if sequence < 0 or sequence > len(events):
            raise CanonicalLedgerCorruption("DURABLE_CURSOR_AHEAD_OF_LEDGER")
        prefix = events[:sequence]
        expected_event_id = prefix[-1]["event_id"] if prefix else None
        if (
            cursor.get("event_id") != expected_event_id
            or cursor.get("ledger_prefix_hash") != _event_stream_hash(prefix)
        ):
            raise CanonicalLedgerCorruption("DURABLE_CURSOR_LEDGER_MISMATCH")
        return sequence

    def _write_cursor(
        self,
        path: Path,
        *,
        consumer: str,
        events: list[dict[str, Any]],
    ) -> None:
        payload = self._cursor_payload(consumer=consumer, events=events)
        ecrire_atomique(
            path,
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        )

    def _segment_paths(self) -> list[Path]:
        root = self.paths.ledger_segments_root
        if not root.is_dir():
            return []
        paths = sorted(root.glob("alerts.*.jsonl"))
        for path in paths:
            if _SEGMENT_RE.fullmatch(path.name) is None:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_SEGMENT_NAME_INVALID:{path.name}"
                )
        return paths

    @staticmethod
    def _segment_receipt(path: Path) -> dict[str, Any]:
        match = _SEGMENT_RE.fullmatch(path.name)
        if match is None:
            raise CanonicalLedgerCorruption(
                f"CANONICAL_SEGMENT_NAME_INVALID:{path.name}"
            )
        raw = path.read_bytes()
        digest = _sha256_bytes(raw)
        if digest != match.group("sha256"):
            raise CanonicalLedgerCorruption(
                f"CANONICAL_SEGMENT_CHECKSUM_MISMATCH:{path.name}"
            )
        return {
            "name": path.name,
            "first_sequence": int(match.group("first")),
            "last_sequence": int(match.group("last")),
            "sha256": digest,
            "bytes": len(raw),
        }

    def _segment_receipts(self) -> list[dict[str, Any]]:
        receipts = [self._segment_receipt(path) for path in self._segment_paths()]
        expected_first = 1
        for receipt in receipts:
            if (
                receipt["first_sequence"] != expected_first
                or receipt["last_sequence"] < receipt["first_sequence"]
            ):
                raise CanonicalLedgerCorruption("CANONICAL_SEGMENT_RANGE_INVALID")
            expected_first = int(receipt["last_sequence"]) + 1
        return receipts

    def _latest_pointer_payload(
        self,
        events: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        active_raw = (
            self.paths.ledger_path.read_bytes()
            if self.paths.ledger_path.is_file()
            else b""
        )
        return {
            "schema_version": LEDGER_LATEST_SCHEMA,
            "storage_kind": "NATIVE_JSONL",
            "ledger_sequence": len(events),
            "event_id": events[-1]["event_id"] if events else None,
            "ledger_prefix_hash": _event_stream_hash(list(events)),
            "segments": self._segment_receipts(),
            "active_path": self.paths.ledger_path.name,
            "active_bytes": len(active_raw),
            "active_sha256": _sha256_bytes(active_raw),
            "database_promoted": False,
            "paper_read_only": True,
            "real_execution": False,
        }

    def _write_latest_pointer(self, events: list[Mapping[str, Any]]) -> None:
        payload = self._latest_pointer_payload(events)
        ecrire_atomique(
            self.paths.ledger_latest_pointer_path,
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        )

    def _validate_latest_pointer(
        self,
        events: list[dict[str, Any]],
    ) -> int:
        path = self.paths.ledger_latest_pointer_path
        if not path.is_file():
            return 0
        try:
            pointer = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalLedgerCorruption("CANONICAL_LATEST_POINTER_INVALID") from exc
        if (
            not isinstance(pointer, Mapping)
            or pointer.get("schema_version") != LEDGER_LATEST_SCHEMA
            or pointer.get("storage_kind") != "NATIVE_JSONL"
            or pointer.get("database_promoted") is not False
            or pointer.get("paper_read_only") is not True
            or pointer.get("real_execution") is not False
        ):
            raise CanonicalLedgerCorruption("CANONICAL_LATEST_POINTER_SCHEMA_INVALID")
        try:
            sequence = int(pointer.get("ledger_sequence"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise CanonicalLedgerCorruption(
                "CANONICAL_LATEST_POINTER_SEQUENCE_INVALID"
            ) from exc
        if sequence < 0 or sequence > len(events):
            raise CanonicalLedgerCorruption("CANONICAL_LATEST_POINTER_AHEAD")
        prefix = events[:sequence]
        expected_event_id = prefix[-1]["event_id"] if prefix else None
        if (
            pointer.get("event_id") != expected_event_id
            or pointer.get("ledger_prefix_hash") != _event_stream_hash(prefix)
        ):
            raise CanonicalLedgerCorruption("CANONICAL_LATEST_POINTER_MISMATCH")
        if sequence == len(events):
            expected = self._latest_pointer_payload(events)
            if dict(pointer) != expected:
                raise CanonicalLedgerCorruption(
                    "CANONICAL_LATEST_POINTER_STORAGE_MISMATCH"
                )
        return sequence

    def read_ledger(self) -> list[dict[str, Any]]:
        sources = self._segment_paths()
        if self.paths.ledger_path.is_file():
            sources.append(self.paths.ledger_path)
        events: list[dict[str, Any]] = []
        by_event_id: dict[str, dict[str, Any]] = {}
        for path in sources:
            raw = path.read_bytes()
            if path != self.paths.ledger_path:
                self._segment_receipt(path)
            if raw and not raw.endswith(b"\n"):
                raise CanonicalLedgerCorruption(
                    "CANONICAL_LEDGER_TRAILING_PARTIAL_RECORD"
                )
            first_sequence = len(events) + 1
            for line in raw.splitlines():
                line_number = len(events) + 1
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CanonicalLedgerCorruption(
                        f"CANONICAL_LEDGER_JSON_INVALID:{line_number}"
                    ) from exc
                try:
                    event = _validate_canonical_event(
                        event,
                        expected_sequence=line_number,
                        prior_by_id=by_event_id,
                    )
                except AlertValidationError as exc:
                    raise CanonicalLedgerCorruption(
                        f"CANONICAL_LEDGER_EVENT_INVALID:{line_number}:{exc}"
                    ) from exc
                event_id = str(event["event_id"])
                if event_id in by_event_id:
                    raise CanonicalLedgerCorruption(
                        f"CANONICAL_LEDGER_EVENT_ID_DUPLICATE:{line_number}"
                    )
                by_event_id[event_id] = event
                events.append(event)
            if path != self.paths.ledger_path:
                receipt = self._segment_receipt(path)
                if (
                    receipt["first_sequence"] != first_sequence
                    or receipt["last_sequence"] != len(events)
                ):
                    raise CanonicalLedgerCorruption(
                        "CANONICAL_SEGMENT_CONTENT_RANGE_MISMATCH"
                    )
        self._validate_latest_pointer(events)
        return events

    def _rotate_ledger_if_needed(
        self,
        events: list[dict[str, Any]],
    ) -> Path | None:
        path = self.paths.ledger_path
        if not path.is_file() or path.stat().st_size < self.ledger_rotate_bytes:
            return None
        raw = path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise CanonicalLedgerCorruption(
                "CANONICAL_LEDGER_ROTATION_SOURCE_INVALID"
            )
        line_count = len(raw.splitlines())
        first_sequence = len(events) - line_count + 1
        last_sequence = len(events)
        if first_sequence < 1 or last_sequence < first_sequence:
            raise CanonicalLedgerCorruption("CANONICAL_LEDGER_ROTATION_RANGE_INVALID")
        digest = _sha256_bytes(raw)
        target = self.paths.ledger_segments_root / (
            f"alerts.{first_sequence:020d}-{last_sequence:020d}.{digest}.jsonl"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise CanonicalLedgerCorruption(
                    "CANONICAL_LEDGER_ROTATION_COLLISION"
                )
            path.unlink()
        else:
            os.replace(path, target)
        return target

    def _pending_paths(self) -> list[Path]:
        if not self.paths.pending_root.is_dir():
            return []
        return sorted(self.paths.pending_root.glob("*/*.json"))

    def _inflight_paths(self) -> list[Path]:
        if not self.paths.inflight_root.is_dir():
            return []
        return sorted(self.paths.inflight_root.glob("*/*.json"))

    def _prepare(
        self,
        pending_path: Path,
        *,
        ledger_sequence: int,
        prior_by_id: Mapping[str, Mapping[str, Any]],
    ) -> Path:
        proposal = _validate_proposal(json.loads(pending_path.read_text(encoding="utf-8")))
        if pending_path.parent.name != proposal["producer_id"]:
            raise AlertValidationError("PRODUCER_INBOX_NAMESPACE_MISMATCH")
        source = proposal["source_receipt"]
        admitted_at_ms = int(self.clock_ms())
        if admitted_at_ms < proposal["verified_at_ms"]:
            raise AlertValidationError("ADMITTED_BEFORE_VERIFIED")
        same_epoch = [
            previous
            for previous in prior_by_id.values()
            if previous.get("producer_id") == proposal["producer_id"]
            and previous.get("producer_epoch") == proposal["producer_epoch"]
        ]
        candidate_identity = {
            "source_id": source["source_id"],
            "dedup_key": proposal["dedup_key"],
            "source_content_hash": source["source_content_hash"],
            "source_event_id": proposal["source_event_id"],
            "revision_of": proposal["revision_of"],
            "retracts": proposal["retracts"],
        }
        candidate_event_id = _sha256(_event_identity(candidate_identity))
        existing = prior_by_id.get(candidate_event_id)
        if existing is not None:
            expected_producer_seq = int(existing["producer_expected_seq"])
            producer_gap_size = int(existing["producer_gap_size"])
        else:
            expected_producer_seq = (
                max(int(previous["producer_seq"]) for previous in same_epoch) + 1
                if same_epoch
                else 0
            )
            if proposal["producer_seq"] < expected_producer_seq:
                raise AlertValidationError("PRODUCER_SEQUENCE_OUT_OF_ORDER")
            producer_gap_size = proposal["producer_seq"] - expected_producer_seq
        event = {
            "schema_version": EVENT_SCHEMA,
            "ledger_sequence": int(ledger_sequence),
            "proposal_id": proposal["proposal_id"],
            "producer_id": proposal["producer_id"],
            "producer_epoch": proposal["producer_epoch"],
            "producer_seq": proposal["producer_seq"],
            "producer_expected_seq": expected_producer_seq,
            "producer_gap_detected": producer_gap_size > 0,
            "producer_gap_size": producer_gap_size,
            "source_receipt": source,
            "source_receipt_hash": proposal["source_receipt_hash"],
            "source_id": source["source_id"],
            "source_uri": source["source_uri"],
            "source_content_hash": source["source_content_hash"],
            "source_event_id": proposal["source_event_id"],
            "source_event_time_ms": proposal["source_event_time_ms"],
            "source_publish_time_ms": proposal["source_publish_time_ms"],
            "source_available_time_ms": proposal["source_available_time_ms"],
            "source_available_time_origin": proposal[
                "source_available_time_origin"
            ],
            "source_available_at_ms": proposal["source_available_time_ms"],
            "availability_lag_ms": (
                proposal["observed_at_ms"] - proposal["source_available_time_ms"]
            ),
            "observed_at_ms": proposal["observed_at_ms"],
            "fetched_at_ms": proposal["fetched_at_ms"],
            "parsed_at_ms": proposal["parsed_at_ms"],
            "parsed_at_origin": proposal["parsed_at_origin"],
            "verified_at_ms": proposal["verified_at_ms"],
            "admitted_at_ms": admitted_at_ms,
            "expires_at_ms": proposal["expires_at_ms"],
            "category": proposal["category"],
            "headline": proposal["headline"],
            "dedup_key": proposal["dedup_key"],
            "dedup_key_origin": proposal["dedup_key_origin"],
            "entity_ids": proposal["entity_ids"],
            "normalized_tickers": proposal["normalized_tickers"],
            "revision_of": proposal["revision_of"],
            "retracts": proposal["retracts"],
            "evidence_refs": proposal["evidence_refs"],
            "source_health_state": proposal["source_health_state"],
            "freshness_state": proposal["freshness_state"],
            "deterministic_score_components": proposal[
                "deterministic_score_components"
            ],
            "deterministic_score": proposal["deterministic_score"],
            "deterministic_score_receipt": proposal[
                "deterministic_score_receipt"
            ],
            "model_opinion": proposal["model_opinion"],
            "economic_admission_state": proposal["economic_admission_state"],
            "order_intent_allowed": proposal["order_intent_allowed"],
            "policy_version": proposal["policy_version"],
            "ingestion_code_sha": proposal["ingestion_code_sha"],
            "payload": proposal["payload"],
            "payload_hash": proposal["payload_hash"],
            "lifecycle_state": "ADMITTED",
            "lifecycle_receipt": [
                {"state": "DETECTED", "at_ms": proposal["observed_at_ms"]},
                {"state": "FETCHED", "at_ms": proposal["fetched_at_ms"]},
                {"state": "VERIFIED", "at_ms": proposal["verified_at_ms"]},
                {"state": "ADMITTED", "at_ms": admitted_at_ms},
            ],
            "paper_read_only": True,
            "real_execution": False,
        }
        event["event_id"] = candidate_event_id
        event = _validate_canonical_event(
            event,
            expected_sequence=ledger_sequence,
            prior_by_id=prior_by_id,
        )
        prepared = {
            "schema_version": "hypersmart.alert_inflight.v1",
            "pending_path": str(pending_path.relative_to(self.paths.pending_root)),
            "event": event,
        }
        target = (
            self.paths.inflight_root
            / proposal["producer_id"]
            / pending_path.name
        )
        ecrire_atomique(
            target,
            json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n",
        )
        return target

    def _load_inflight(self, path: Path) -> tuple[Path, dict[str, Any]]:
        prepared = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(prepared, Mapping) or prepared.get("schema_version") != "hypersmart.alert_inflight.v1":
            raise AlertValidationError("INFLIGHT_SCHEMA_INVALID")
        relative = Path(str(prepared.get("pending_path") or ""))
        pending = (self.paths.pending_root / relative).resolve()
        if not _is_within(pending, self.paths.pending_root):
            raise AlertValidationError("INFLIGHT_PENDING_PATH_ESCAPE")
        event = prepared.get("event")
        if not isinstance(event, dict):
            raise AlertValidationError("INFLIGHT_EVENT_INVALID")
        return pending, _validate_canonical_event(event)

    def _acknowledge(self, pending: Path, inflight: Path) -> None:
        relative = pending.relative_to(self.paths.pending_root)
        acknowledged = self.paths.acknowledged_root / relative
        acknowledged.parent.mkdir(parents=True, exist_ok=True)
        if pending.exists():
            if acknowledged.exists():
                if acknowledged.read_bytes() != pending.read_bytes():
                    raise AlertSpineError("ACKNOWLEDGED_PROPOSAL_COLLISION")
                pending.unlink()
            else:
                os.replace(pending, acknowledged)
        elif not acknowledged.is_file():
            raise AlertSpineError("PENDING_AND_ACK_MISSING")
        inflight.unlink(missing_ok=True)

    def process_pending(
        self,
        *,
        max_events: int | None = None,
        after_prepare: Callable[[Mapping[str, Any]], None] | None = None,
        after_append: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        accepted = 0
        deduplicated = 0
        with SingleWriterFileLock(self.paths.writer_lock_path):
            events = self.read_ledger()
            self._validate_cursor(
                self.paths.writer_cursor_path,
                consumer="canonical-writer",
                events=events,
            )
            by_event_id = {str(event["event_id"]): event for event in events}
            while max_events is None or accepted + deduplicated < max_events:
                inflight_paths = self._inflight_paths()
                if inflight_paths:
                    inflight = inflight_paths[0]
                else:
                    pending_paths = self._pending_paths()
                    if not pending_paths:
                        break
                    inflight = self._prepare(
                        pending_paths[0],
                        ledger_sequence=len(events) + 1,
                        prior_by_id=by_event_id,
                    )
                    if after_prepare is not None:
                        _, prepared_event = self._load_inflight(inflight)
                        after_prepare(prepared_event)
                pending, event = self._load_inflight(inflight)
                event = _validate_canonical_event(
                    event,
                    prior_by_id=by_event_id,
                )
                event_id = str(event.get("event_id") or "")
                existing = by_event_id.get(event_id)
                if existing is not None:
                    non_economic_metadata = {
                        "ledger_sequence",
                        "admitted_at_ms",
                        "proposal_id",
                        "producer_id",
                        "producer_epoch",
                        "producer_seq",
                        "producer_expected_seq",
                        "producer_gap_detected",
                        "producer_gap_size",
                        "lifecycle_receipt",
                        "model_opinion",
                    }
                    comparable_existing = {
                        key: value
                        for key, value in existing.items()
                        if key not in non_economic_metadata
                    }
                    comparable_event = {
                        key: value
                        for key, value in event.items()
                        if key not in non_economic_metadata
                    }
                    if comparable_existing != comparable_event:
                        raise CanonicalLedgerCorruption("EVENT_ID_CONTENT_COLLISION")
                    self._acknowledge(pending, inflight)
                    self._write_cursor(
                        self.paths.writer_cursor_path,
                        consumer="canonical-writer",
                        events=events,
                    )
                    deduplicated += 1
                    continue
                if event.get("ledger_sequence") != len(events) + 1:
                    raise CanonicalLedgerCorruption("INFLIGHT_SEQUENCE_STALE")
                jsonl_append_fsync(self.paths.ledger_path, event)
                events.append(event)
                by_event_id[event_id] = event
                self._rotate_ledger_if_needed(events)
                self._write_latest_pointer(events)
                if after_append is not None:
                    after_append(event)
                self._acknowledge(pending, inflight)
                self._write_cursor(
                    self.paths.writer_cursor_path,
                    consumer="canonical-writer",
                    events=events,
                )
                accepted += 1
            self._write_cursor(
                self.paths.writer_cursor_path,
                consumer="canonical-writer",
                events=events,
            )
            self._write_latest_pointer(events)
            projection = self.rebuild_projection(events=events)
        return {
            "schema_version": "hypersmart.alert_writer_run.v1",
            "accepted": accepted,
            "deduplicated": deduplicated,
            "ledger_count": len(events),
            "projection_count": projection["alert_count"],
            "paper_read_only": True,
            "real_execution": False,
        }

    def rebuild_projection(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        displayed_at_ms: int | None = None,
    ) -> dict[str, Any]:
        replayed = self.read_ledger() if events is None else list(events)
        self._validate_cursor(
            self.paths.projection_cursor_path,
            consumer="dashboard-projection",
            events=replayed,
        )
        projected_at_ms = int(self.clock_ms())
        if any(projected_at_ms < int(event["admitted_at_ms"]) for event in replayed):
            raise AlertValidationError("PROJECTED_BEFORE_ADMITTED")
        if displayed_at_ms is not None:
            displayed_at_ms = int(displayed_at_ms)
            if displayed_at_ms < projected_at_ms:
                raise AlertValidationError("DISPLAYED_BEFORE_PROJECTED")
        states = {
            str(event["event_id"]): (
                "EXPIRED"
                if event.get("expires_at_ms") is not None
                and projected_at_ms >= int(event["expires_at_ms"])
                else "PROJECTED"
            )
            for event in replayed
        }
        for event in replayed:
            revision_of = event.get("revision_of")
            retracts = event.get("retracts")
            if revision_of is not None:
                states[str(revision_of)] = "CORRECTED"
            if retracts is not None:
                states[str(retracts)] = "RETRACTED"
        freshness_projection = project_alert_freshness(
            replayed,
            projected_at_ms=projected_at_ms,
            displayed_at_ms=displayed_at_ms,
        )
        projected_alerts = [
            {
                **event,
                "projection_lifecycle_state": states[str(event["event_id"])],
                "effective_freshness_state": freshness_projection[
                    "event_states"
                ][str(event["event_id"])]["effective_freshness_state"],
                "effective_source_health_state": freshness_projection[
                    "event_states"
                ][str(event["event_id"])]["effective_source_health_state"],
                "no_news_conclusion_valid": freshness_projection["event_states"][
                    str(event["event_id"])
                ]["no_news_conclusion_valid"],
            }
            for event in replayed
        ]
        telemetry: dict[str, int] = {"projected_at_ms": projected_at_ms}
        if displayed_at_ms is not None:
            telemetry["displayed_at_ms"] = displayed_at_ms
        deterministic_projection = {
            "schema_version": PROJECTION_SCHEMA,
            "last_ledger_sequence": len(replayed),
            "alert_count": len(replayed),
            "alerts": projected_alerts,
        }
        projection = {
            **deterministic_projection,
            "derived_from": str(self.paths.ledger_path),
            "canonical_projection_hash": _sha256(deterministic_projection),
            "freshness": freshness_projection,
            "projection_telemetry": telemetry,
            "paper_read_only": True,
            "real_execution": False,
        }
        ecrire_atomique(
            self.paths.projection_path,
            json.dumps(projection, ensure_ascii=False, sort_keys=True) + "\n",
        )
        self._write_cursor(
            self.paths.projection_cursor_path,
            consumer="dashboard-projection",
            events=replayed,
        )
        return projection


__all__ = [
    "AlertProducerInbox",
    "AlertSpineError",
    "AlertSpinePaths",
    "AlertValidationError",
    "CanonicalAlertWriter",
    "CanonicalLedgerCorruption",
    "EVENT_SCHEMA",
    "PROJECTION_SCHEMA",
    "PROPOSAL_SCHEMA",
    "SingleWriterFileLock",
    "WriterBusy",
    "build_alert_proposal",
    "jsonl_append_fsync",
]
