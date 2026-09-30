"""Pure alert proposal validation and deterministic construction."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
