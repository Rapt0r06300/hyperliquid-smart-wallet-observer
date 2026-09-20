"""Tamper-evident append-only R1/R2 archive for Event Intelligence."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent

ARCHIVE_SCHEMA = "alina.event_intelligence_archive.v1"
DEFAULT_ARCHIVE_PATH = (
    Path("runtime") / "data" / "event_intelligence" / "events_r2.jsonl"
)


class EventArchiveCorruptError(RuntimeError):
    """Raised when existing archive evidence cannot be verified."""


@dataclass(frozen=True, slots=True)
class ArchiveAppendResult:
    appended: bool
    sequence: int
    record_sha256: str
    reason: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class EventIntelligenceArchive:
    """Append-only JSONL with persistent dedupe and a SHA-256 record chain."""

    def __init__(self, path: str | Path = DEFAULT_ARCHIVE_PATH) -> None:
        self.path = Path(path)
        self._seen: dict[tuple[str, str], tuple[int, str]] = {}
        self._last_sequence = 0
        self._last_record_sha256 = ""
        self._load_existing()

    @property
    def count(self) -> int:
        return self._last_sequence

    @property
    def last_record_sha256(self) -> str:
        return self._last_record_sha256

    def append(self, event: WorldMonitorEvent) -> ArchiveAppendResult:
        payload = event.to_archive_record()
        key = _dedupe_key(payload)
        existing = self._seen.get(key)
        if existing is not None:
            return ArchiveAppendResult(
                appended=False,
                sequence=existing[0],
                record_sha256=existing[1],
                reason="DUPLICATE_EVENT",
            )

        sequence = self._last_sequence + 1
        payload_sha256 = _sha256(payload)
        body = {
            "schema": ARCHIVE_SCHEMA,
            "sequence": sequence,
            "previous_record_sha256": self._last_record_sha256,
            "payload_sha256": payload_sha256,
            "payload": payload,
        }
        record_sha256 = _sha256(body)
        record = {**body, "record_sha256": record_sha256}

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

        self._last_sequence = sequence
        self._last_record_sha256 = record_sha256
        self._seen[key] = (sequence, record_sha256)
        return ArchiveAppendResult(
            appended=True,
            sequence=sequence,
            record_sha256=record_sha256,
            reason="APPENDED",
        )

    def append_many(
        self,
        events: Iterable[WorldMonitorEvent],
    ) -> list[ArchiveAppendResult]:
        return [self.append(event) for event in events]

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        previous_sha256 = ""
        expected_sequence = 1
        try:
            handle = self.path.open("r", encoding="utf-8")
        except OSError as exc:
            raise EventArchiveCorruptError(
                f"ARCHIVE_OPEN_FAILED:{exc.__class__.__name__}"
            ) from exc

        with handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_BLANK_RECORD:{line_number}"
                    )
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_JSON_INVALID:{line_number}"
                    ) from exc
                if not isinstance(record, dict):
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_RECORD_NOT_OBJECT:{line_number}"
                    )
                if record.get("schema") != ARCHIVE_SCHEMA:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_SCHEMA_INVALID:{line_number}"
                    )
                if record.get("sequence") != expected_sequence:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_SEQUENCE_INVALID:{line_number}"
                    )
                if record.get("previous_record_sha256") != previous_sha256:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_CHAIN_INVALID:{line_number}"
                    )
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_PAYLOAD_INVALID:{line_number}"
                    )
                payload_sha256 = _sha256(payload)
                if record.get("payload_sha256") != payload_sha256:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_PAYLOAD_HASH_INVALID:{line_number}"
                    )
                body = {
                    "schema": record.get("schema"),
                    "sequence": record.get("sequence"),
                    "previous_record_sha256": record.get(
                        "previous_record_sha256"
                    ),
                    "payload_sha256": record.get("payload_sha256"),
                    "payload": payload,
                }
                record_sha256 = _sha256(body)
                if record.get("record_sha256") != record_sha256:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_RECORD_HASH_INVALID:{line_number}"
                    )
                key = _dedupe_key(payload)
                if key in self._seen:
                    raise EventArchiveCorruptError(
                        f"ARCHIVE_DUPLICATE_EVENT:{line_number}"
                    )
                self._seen[key] = (expected_sequence, record_sha256)
                previous_sha256 = record_sha256
                expected_sequence += 1

        self._last_sequence = expected_sequence - 1
        self._last_record_sha256 = previous_sha256


def _dedupe_key(payload: dict[str, object]) -> tuple[str, str]:
    source = str(payload.get("source") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    if not source or not event_id:
        raise EventArchiveCorruptError("ARCHIVE_EVENT_IDENTITY_MISSING")
    return source, event_id


__all__ = [
    "ARCHIVE_SCHEMA",
    "ArchiveAppendResult",
    "DEFAULT_ARCHIVE_PATH",
    "EventArchiveCorruptError",
    "EventIntelligenceArchive",
]
