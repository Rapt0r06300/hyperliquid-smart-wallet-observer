"""Crash-safe, hash-chained storage for the local paper ledger.

The state snapshot is a cache.  The durable ledger is the evidence.  Each
rewrite is atomic and fsynced, every row is sequenced, and a malformed row or
broken hash chain blocks strict PnL instead of being skipped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

GENESIS_HASH = "0" * 64
LEDGER_OK = "OK"
LEDGER_CORRUPTED = "LEDGER_CORRUPTED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

_CHAIN_FIELDS = {"event_seq", "event_id", "session_id", "prev_hash", "event_hash"}


@dataclass(frozen=True, slots=True)
class LedgerReadResult:
    status: str
    events: tuple[dict[str, Any], ...]
    errors: tuple[dict[str, Any], ...] = ()

    @property
    def strict_pnl_allowed(self) -> bool:
        return self.status == LEDGER_OK and not self.errors


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_event_id(event: dict[str, Any], *, session_id: str) -> str:
    """Derive an ID from causal content, never wall-clock time at persistence."""

    explicit = event.get("event_id") or event.get("delta_key")
    if explicit:
        return str(explicit)
    semantic = {key: value for key, value in event.items() if key not in _CHAIN_FIELDS}
    digest = sha256(f"{session_id}|{canonical_json(semantic)}".encode("utf-8")).hexdigest()
    return f"pledger:{digest[:32]}"


def seal_event(
    event: dict[str, Any],
    *,
    event_seq: int,
    session_id: str,
    prev_hash: str,
) -> dict[str, Any]:
    if event_seq <= 0:
        raise ValueError("event_seq must be positive")
    if not session_id:
        raise ValueError("session_id is required")
    row = {key: value for key, value in event.items() if key not in _CHAIN_FIELDS}
    row.update(
        {
            "event_seq": int(event_seq),
            "event_id": stable_event_id(event, session_id=session_id),
            "session_id": str(session_id),
            "prev_hash": str(prev_hash),
        }
    )
    row["event_hash"] = sha256(canonical_json(row).encode("utf-8")).hexdigest()
    return row


def seal_chain(events: Iterable[dict[str, Any]], *, session_id: str) -> tuple[dict[str, Any], ...]:
    sealed: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    seen_ids: set[str] = set()
    for seq, raw in enumerate(events, start=1):
        if not isinstance(raw, dict):
            raise TypeError(f"ledger event {seq} is not an object")
        row = seal_event(raw, event_seq=seq, session_id=session_id, prev_hash=previous)
        event_id = str(row["event_id"])
        if event_id in seen_ids:
            raise ValueError(f"duplicate event_id: {event_id}")
        seen_ids.add(event_id)
        sealed.append(row)
        previous = str(row["event_hash"])
    return tuple(sealed)


def verify_chain(events: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows = tuple(events)
    previous = GENESIS_HASH
    session_id: str | None = None
    seen_ids: set[str] = set()
    for expected_seq, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"event {expected_seq} is not an object")
        if row.get("event_seq") != expected_seq:
            raise ValueError(f"non-monotonic event_seq at row {expected_seq}")
        row_session = str(row.get("session_id") or "")
        if not row_session:
            raise ValueError(f"missing session_id at row {expected_seq}")
        if session_id is None:
            session_id = row_session
        elif row_session != session_id:
            raise ValueError(f"session_id changed at row {expected_seq}")
        event_id = str(row.get("event_id") or "")
        if not event_id or event_id in seen_ids:
            raise ValueError(f"missing or duplicate event_id at row {expected_seq}")
        seen_ids.add(event_id)
        if row.get("prev_hash") != previous:
            raise ValueError(f"prev_hash mismatch at row {expected_seq}")
        material = {key: value for key, value in row.items() if key != "event_hash"}
        expected_hash = sha256(canonical_json(material).encode("utf-8")).hexdigest()
        if row.get("event_hash") != expected_hash:
            raise ValueError(f"event_hash mismatch at row {expected_seq}")
        previous = expected_hash
    return rows


def write_chain_atomic(
    path: Path,
    events: Iterable[dict[str, Any]],
    *,
    session_id: str,
) -> tuple[dict[str, Any], ...]:
    """Write a complete verified chain atomically in the destination directory."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = seal_chain(events, session_id=session_id)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()
    return rows


def read_chain(path: Path) -> LedgerReadResult:
    source = Path(path)
    if not source.exists():
        return LedgerReadResult(status=LEDGER_OK, events=())
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    offset = 0
    try:
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                encoded_length = len(line.encode("utf-8"))
                try:
                    parsed = json.loads(line)
                    if not isinstance(parsed, dict):
                        raise ValueError("ledger row is not an object")
                    rows.append(parsed)
                except (json.JSONDecodeError, ValueError) as exc:
                    errors.append(
                        {
                            "line": line_number,
                            "offset": offset,
                            "error": str(exc),
                        }
                    )
                offset += encoded_length
    except OSError as exc:
        return LedgerReadResult(
            status=LEDGER_CORRUPTED,
            events=tuple(rows),
            errors=({"line": 0, "offset": 0, "error": str(exc)},),
        )
    if errors:
        return LedgerReadResult(status=LEDGER_CORRUPTED, events=tuple(rows), errors=tuple(errors))
    try:
        verified = verify_chain(rows)
    except (TypeError, ValueError) as exc:
        return LedgerReadResult(
            status=LEDGER_CORRUPTED,
            events=tuple(rows),
            errors=({"line": 0, "offset": 0, "error": str(exc)},),
        )
    return LedgerReadResult(status=LEDGER_OK, events=verified)


def latest_checkpoint(events: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(tuple(events)):
        if row.get("record_type") == "STATE_CHECKPOINT" and isinstance(row.get("state"), dict):
            return dict(row["state"])
    return None


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "GENESIS_HASH",
    "LEDGER_CORRUPTED",
    "LEDGER_OK",
    "RECOVERY_REQUIRED",
    "LedgerReadResult",
    "canonical_json",
    "latest_checkpoint",
    "read_chain",
    "seal_chain",
    "seal_event",
    "stable_event_id",
    "verify_chain",
    "write_chain_atomic",
]
