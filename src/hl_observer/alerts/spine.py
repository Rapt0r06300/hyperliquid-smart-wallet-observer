"""Durable, local-only alert spine with one canonical writer.

Producers can only create immutable proposals in their own inbox. A single
deterministic writer validates and appends canonical events, then derives a
mutable dashboard projection from that append-only ledger. The module has no
network, shell, model or trading capability.
"""

from __future__ import annotations

import hashlib
import json
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
_MAX_HEADLINE = 1_000
_MAX_DEDUP_KEY = 256


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
    proposal.update(
        {
            "producer_id": producer_id,
            "producer_seq": producer_seq,
            "source_receipt": {
                "source_id": source_id,
                "source_uri": source_uri,
                "source_content_hash": source_hash,
            },
            "observed_at_ms": timestamps[0],
            "fetched_at_ms": timestamps[1],
            "verified_at_ms": timestamps[2],
            "category": category,
            "headline": headline,
            "dedup_key": dedup_key,
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
            "observed_at_ms": observed_at_ms,
            "fetched_at_ms": fetched_at_ms,
            "verified_at_ms": verified_at_ms,
            "category": category,
            "headline": headline,
            "dedup_key": dedup_key,
            "payload": dict(payload or {}),
            "paper_read_only": True,
            "real_execution": False,
        }
    )


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
        seen: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_LEDGER_JSON_INVALID:{line_number}"
                ) from exc
            if not isinstance(event, dict) or event.get("schema_version") != EVENT_SCHEMA:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_LEDGER_SCHEMA_INVALID:{line_number}"
                )
            event_id = str(event.get("event_id") or "")
            if not _SHA256_RE.fullmatch(event_id) or event_id in seen:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_LEDGER_EVENT_ID_INVALID:{line_number}"
                )
            if event.get("ledger_sequence") != line_number:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_LEDGER_SEQUENCE_INVALID:{line_number}"
                )
            if event.get("paper_read_only") is not True or event.get("real_execution") is not False:
                raise CanonicalLedgerCorruption(
                    f"CANONICAL_LEDGER_SAFETY_INVALID:{line_number}"
                )
            seen.add(event_id)
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
        event_identity = {
            "dedup_key": proposal["dedup_key"],
            "source_content_hash": source["source_content_hash"],
        }
        event = {
            "schema_version": EVENT_SCHEMA,
            "event_id": _sha256(event_identity),
            "ledger_sequence": int(ledger_sequence),
            "proposal_id": proposal["proposal_id"],
            "producer_id": proposal["producer_id"],
            "producer_seq": proposal["producer_seq"],
            "source_id": source["source_id"],
            "source_uri": source["source_uri"],
            "source_content_hash": source["source_content_hash"],
            "observed_at_ms": proposal["observed_at_ms"],
            "fetched_at_ms": proposal["fetched_at_ms"],
            "verified_at_ms": proposal["verified_at_ms"],
            "admitted_at_ms": int(self.clock_ms()),
            "category": proposal["category"],
            "headline": proposal["headline"],
            "dedup_key": proposal["dedup_key"],
            "payload": proposal["payload"],
            "paper_read_only": True,
            "real_execution": False,
        }
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
        return pending, event

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
    ) -> dict[str, Any]:
        replayed = self.read_ledger() if events is None else list(events)
        projection = {
            "schema_version": PROJECTION_SCHEMA,
            "derived_from": str(self.paths.ledger_path),
            "last_ledger_sequence": len(replayed),
            "alert_count": len(replayed),
            "alerts": replayed,
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
