"""Durable alert-spine primitives and canonical-event validation.

This module is local-only and preserves the alert spine fail-closed,
paper/read-only contract. It has no network, shell, model, signing or
trading capability.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.alerts.validation import (
    _CODE_SHA_RE,
    _MAX_DEDUP_KEY,
    _MAX_HEADLINE,
    _SEGMENT_RE,
    _SHA256_RE,
    EVENT_SCHEMA,
    FRESHNESS_STATES,
    LEDGER_LATEST_SCHEMA,
    SOURCE_HEALTH_STATES,
    AlertSpineError,
    AlertValidationError,
    CanonicalLedgerCorruption,
    WriterBusy,
    _bounded_strings,
    _canonical_bytes,
    _event_identity,
    _event_reference,
    _event_stream_hash,
    _evidence_refs,
    _is_within,
    _reject_order_capability,
    _score_components,
    _score_receipt,
    _sha256,
    _sha256_bytes,
    _validate_lifecycle_receipt,
    _validate_producer_epoch,
    _validate_producer_id,
    _validate_proposal,
)
from hl_observer.collection.collecte_fiable import append_jsonl, ecrire_atomique


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


class CanonicalAlertDurabilityMixin:
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
