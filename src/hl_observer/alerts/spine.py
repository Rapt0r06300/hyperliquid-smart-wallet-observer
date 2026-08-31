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
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.collection.collecte_fiable import append_jsonl, ecrire_atomique

PROPOSAL_SCHEMA = "hypersmart.alert_proposal.v1"
EVENT_SCHEMA = "hypersmart.canonical_alert_event.v1"
PROJECTION_SCHEMA = "hypersmart.alert_projection.v1"
_PRODUCER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
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
    components: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key or len(key) > 128:
            raise AlertValidationError("DETERMINISTIC_SCORE_COMPONENTS_INVALID")
        try:
            number = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "DETERMINISTIC_SCORE_COMPONENTS_INVALID"
            ) from exc
        if not math.isfinite(number):
            raise AlertValidationError("DETERMINISTIC_SCORE_COMPONENTS_INVALID")
        components[key] = number
    return dict(sorted(components.items()))


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
    source_event_time_raw = proposal.get("source_event_time_ms")
    source_event_time_ms: int | None = None
    if source_event_time_raw is not None:
        try:
            source_event_time_ms = int(source_event_time_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError("TIMESTAMP_INVALID:source_event_time_ms") from exc
        if source_event_time_ms < 0 or source_event_time_ms > timestamps[0]:
            raise AlertValidationError("SOURCE_EVENT_TIME_IMPOSSIBLE")
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
    if not dedup_key or len(dedup_key) > _MAX_DEDUP_KEY:
        raise AlertValidationError("DEDUP_KEY_INVALID")
    if proposal.get("paper_read_only") is not True or proposal.get("real_execution") is not False:
        raise AlertValidationError("PAPER_READ_ONLY_REQUIRED")
    if not isinstance(proposal.get("payload", {}), Mapping):
        raise AlertValidationError("PAYLOAD_NOT_MAPPING")
    entity_ids = _bounded_strings(proposal.get("entity_ids"), field="entity_ids")
    normalized_tickers = _bounded_strings(
        proposal.get("normalized_tickers"),
        field="normalized_tickers",
        uppercase=True,
    )
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
    components = _score_components(proposal.get("deterministic_score_components"))
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
            "producer_seq": producer_seq,
            "source_receipt": source_receipt,
            "source_receipt_hash": _sha256(source_receipt),
            "source_event_time_ms": source_event_time_ms,
            "observed_at_ms": timestamps[0],
            "fetched_at_ms": timestamps[1],
            "verified_at_ms": timestamps[2],
            "expires_at_ms": expires_at_ms,
            "category": category,
            "headline": headline,
            "dedup_key": dedup_key,
            "entity_ids": entity_ids,
            "normalized_tickers": normalized_tickers,
            "evidence_refs": evidence_refs,
            "source_health_state": source_health_state,
            "freshness_state": freshness_state,
            "deterministic_score_components": components,
            "model_opinion": model_opinion,
            "policy_version": policy_version,
            "ingestion_code_sha": ingestion_code_sha,
            "revision_of": revision_of,
            "retracts": retracts,
            "payload": dict(proposal.get("payload") or {}),
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
    producer_seq: int,
    source_id: str,
    source_uri: str,
    source_content_hash: str,
    observed_at_ms: int,
    fetched_at_ms: int,
    verified_at_ms: int,
    category: str,
    headline: str,
    dedup_key: str,
    policy_version: str,
    ingestion_code_sha: str,
    source_event_time_ms: int | None = None,
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
            "producer_seq": producer_seq,
            "source_receipt": {
                "source_id": source_id,
                "source_uri": source_uri,
                "source_content_hash": source_content_hash,
            },
            "source_event_time_ms": source_event_time_ms,
            "observed_at_ms": observed_at_ms,
            "fetched_at_ms": fetched_at_ms,
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
    return {
        "source_id": event.get("source_id"),
        "dedup_key": event.get("dedup_key"),
        "source_content_hash": event.get("source_content_hash"),
        "revision_of": event.get("revision_of"),
        "retracts": event.get("retracts"),
    }


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

    times: list[int] = []
    for field in (
        "observed_at_ms",
        "fetched_at_ms",
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
    expires_at = event.get("expires_at_ms")
    if expires_at is not None:
        try:
            expires_at = int(expires_at)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AlertValidationError(
                "CANONICAL_TIMESTAMP_INVALID:expires_at_ms"
            ) from exc
        if expires_at < times[3]:
            raise AlertValidationError("CANONICAL_EXPIRES_AT_IMPOSSIBLE")

    category = str(event.get("category") or "").strip().upper()
    headline = str(event.get("headline") or "").strip()
    dedup_key = str(event.get("dedup_key") or "").strip()
    if not category or not headline or len(headline) > _MAX_HEADLINE:
        raise AlertValidationError("CANONICAL_ALERT_CONTENT_INVALID")
    if not dedup_key or len(dedup_key) > _MAX_DEDUP_KEY:
        raise AlertValidationError("CANONICAL_DEDUP_KEY_INVALID")
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
    if event.get("deterministic_score_components") != _score_components(
        event.get("deterministic_score_components")
    ):
        raise AlertValidationError("CANONICAL_SCORE_COMPONENTS_NOT_NORMALIZED")
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
    if event.get("paper_read_only") is not True or event.get("real_execution") is not False:
        raise AlertValidationError("CANONICAL_PAPER_READ_ONLY_REQUIRED")
    if "displayed_at_ms" in event or "projected_at_ms" in event:
        raise AlertValidationError("PROJECTION_TELEMETRY_IN_IMMUTABLE_EVENT")
    if event_id != _sha256(_event_identity(event)):
        raise AlertValidationError("CANONICAL_EVENT_ID_MISMATCH")
    _validate_lifecycle_receipt(event)

    if prior_by_id is not None:
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
            "producer_seq": producer_seq,
            "ledger_sequence": ledger_sequence,
            "source_event_time_ms": source_event_time,
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
    projection_path: Path
    writer_lock_path: Path

    @classmethod
    def from_root(cls, root: str | Path) -> AlertSpinePaths:
        base = Path(root).resolve()
        paths = cls(
            root=base,
            pending_root=base / "producer_inboxes" / "pending",
            inflight_root=base / "writer_state" / "inflight",
            acknowledged_root=base / "producer_inboxes" / "acknowledged",
            ledger_path=base / "canonical" / "alerts.jsonl",
            projection_path=base / "projections" / "alerts_dashboard.json",
            writer_lock_path=base / "writer_state" / "canonical_writer.lock",
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
        try:
            descriptor = os.open(
                str(target),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            if target.read_bytes() != encoded:
                raise AlertValidationError("PROPOSAL_PATH_COLLISION") from exc
            return target
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return target


class CanonicalAlertWriter:
    """The only authority allowed to append and project canonical alerts."""

    def __init__(
        self,
        paths: AlertSpinePaths,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.paths = paths
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def producer(self, producer_id: str) -> AlertProducerInbox:
        return AlertProducerInbox(self.paths.pending_root, producer_id)

    def read_ledger(self) -> list[dict[str, Any]]:
        path = self.paths.ledger_path
        if not path.is_file():
            return []
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise CanonicalLedgerCorruption("CANONICAL_LEDGER_TRAILING_PARTIAL_RECORD")
        events: list[dict[str, Any]] = []
        by_event_id: dict[str, dict[str, Any]] = {}
        for line_number, line in enumerate(raw.splitlines(), start=1):
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
        return events

    def _pending_paths(self) -> list[Path]:
        if not self.paths.pending_root.is_dir():
            return []
        return sorted(self.paths.pending_root.glob("*/*.json"))

    def _inflight_paths(self) -> list[Path]:
        if not self.paths.inflight_root.is_dir():
            return []
        return sorted(self.paths.inflight_root.glob("*/*.json"))

    def _prepare(self, pending_path: Path, *, ledger_sequence: int) -> Path:
        proposal = _validate_proposal(json.loads(pending_path.read_text(encoding="utf-8")))
        if pending_path.parent.name != proposal["producer_id"]:
            raise AlertValidationError("PRODUCER_INBOX_NAMESPACE_MISMATCH")
        source = proposal["source_receipt"]
        admitted_at_ms = int(self.clock_ms())
        if admitted_at_ms < proposal["verified_at_ms"]:
            raise AlertValidationError("ADMITTED_BEFORE_VERIFIED")
        event = {
            "schema_version": EVENT_SCHEMA,
            "ledger_sequence": int(ledger_sequence),
            "proposal_id": proposal["proposal_id"],
            "producer_id": proposal["producer_id"],
            "producer_seq": proposal["producer_seq"],
            "source_receipt": source,
            "source_receipt_hash": proposal["source_receipt_hash"],
            "source_id": source["source_id"],
            "source_uri": source["source_uri"],
            "source_content_hash": source["source_content_hash"],
            "source_event_time_ms": proposal["source_event_time_ms"],
            "observed_at_ms": proposal["observed_at_ms"],
            "fetched_at_ms": proposal["fetched_at_ms"],
            "verified_at_ms": proposal["verified_at_ms"],
            "admitted_at_ms": admitted_at_ms,
            "expires_at_ms": proposal["expires_at_ms"],
            "category": proposal["category"],
            "headline": proposal["headline"],
            "dedup_key": proposal["dedup_key"],
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
            "model_opinion": proposal["model_opinion"],
            "policy_version": proposal["policy_version"],
            "ingestion_code_sha": proposal["ingestion_code_sha"],
            "payload": proposal["payload"],
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
        event["event_id"] = _sha256(_event_identity(event))
        event = _validate_canonical_event(event, expected_sequence=ledger_sequence)
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
                    comparable_existing = {
                        key: value
                        for key, value in existing.items()
                        if key not in {"ledger_sequence", "admitted_at_ms", "proposal_id", "producer_id", "producer_seq"}
                    }
                    comparable_event = {
                        key: value
                        for key, value in event.items()
                        if key not in {"ledger_sequence", "admitted_at_ms", "proposal_id", "producer_id", "producer_seq"}
                    }
                    if comparable_existing != comparable_event:
                        raise CanonicalLedgerCorruption("EVENT_ID_CONTENT_COLLISION")
                    self._acknowledge(pending, inflight)
                    deduplicated += 1
                    continue
                if event.get("ledger_sequence") != len(events) + 1:
                    raise CanonicalLedgerCorruption("INFLIGHT_SEQUENCE_STALE")
                jsonl_append_fsync(self.paths.ledger_path, event)
                if after_append is not None:
                    after_append(event)
                events.append(event)
                by_event_id[event_id] = event
                self._acknowledge(pending, inflight)
                accepted += 1
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
        projected_alerts = [
            {
                **event,
                "projection_lifecycle_state": states[str(event["event_id"])],
            }
            for event in replayed
        ]
        telemetry: dict[str, int] = {"projected_at_ms": projected_at_ms}
        if displayed_at_ms is not None:
            telemetry["displayed_at_ms"] = displayed_at_ms
        projection = {
            "schema_version": PROJECTION_SCHEMA,
            "derived_from": str(self.paths.ledger_path),
            "last_ledger_sequence": len(replayed),
            "alert_count": len(replayed),
            "alerts": projected_alerts,
            "projection_telemetry": telemetry,
            "paper_read_only": True,
            "real_execution": False,
        }
        ecrire_atomique(
            self.paths.projection_path,
            json.dumps(projection, ensure_ascii=False, sort_keys=True) + "\n",
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
