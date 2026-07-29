"""Transactional, restart-safe event deduplication.

The canonical store uses SQLite instead of a best-effort text file.  A unique
primary key makes check-and-mark atomic across processes, and compaction first
archives evicted identities before deleting them from the live window.
Corruption is explicit and blocks the consumer; it is never interpreted as an
empty dedup store.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class DurableDedupError(RuntimeError):
    """Base class for durable dedup failures."""


class DurableDedupCorruption(DurableDedupError):
    """Raised when the persistent store cannot be read safely."""


@dataclass(frozen=True, slots=True)
class DedupDecision:
    event_id: str
    duplicate: bool
    row_sequence: int | None


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DurableEventDedup:
    """A bounded live dedup window with immutable JSONL archives."""

    def __init__(
        self,
        directory: str | Path,
        *,
        max_entries: int = 200_000,
        compact_every: int = 50_000,
    ) -> None:
        if max_entries < 1 or compact_every < 1:
            raise ValueError("dedup limits must be positive")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database_path = self.directory / "dedup.sqlite3"
        self.archive_directory = self.directory / "archives"
        self.max_entries = int(max_entries)
        self.compact_every = int(compact_every)
        self._writes_since_compaction = 0
        self._archive_sequence = 0
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=30.0,
                isolation_level=None,
            )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"cannot open durable dedup store: {self.database_path}"
            ) from exc

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                if not integrity or str(integrity[0]).lower() != "ok":
                    raise DurableDedupCorruption(
                        f"dedup integrity check failed: {integrity!r}"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS seen_events (
                        row_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        seen_at_ms INTEGER NOT NULL,
                        payload_hash TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS ix_seen_events_seen_at "
                    "ON seen_events(seen_at_ms, row_sequence)"
                )
        except DurableDedupCorruption:
            raise
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"cannot initialize durable dedup store: {self.database_path}"
            ) from exc

    def check_and_mark(
        self,
        event_id: str,
        *,
        seen_at_ms: int | None = None,
        payload_hash: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DedupDecision:
        key = str(event_id).strip()
        if not key:
            raise ValueError("event_id must not be empty")
        timestamp = int(time.time() * 1000 if seen_at_ms is None else seen_at_ms)
        metadata_json = json.dumps(
            dict(metadata or {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT row_sequence FROM seen_events WHERE event_id = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    connection.execute("COMMIT")
                    return DedupDecision(key, True, int(existing[0]))
                cursor = connection.execute(
                    """
                    INSERT INTO seen_events(
                        event_id, seen_at_ms, payload_hash, metadata_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (key, timestamp, payload_hash, metadata_json),
                )
                sequence = int(cursor.lastrowid)
                connection.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"durable dedup write failed: {self.database_path}"
            ) from exc
        self._writes_since_compaction += 1
        if self._writes_since_compaction >= self.compact_every:
            self.compact()
        return DedupDecision(key, False, sequence)

    def contains(self, event_id: str) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM seen_events WHERE event_id = ?",
                    (str(event_id),),
                ).fetchone()
                return row is not None
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"durable dedup read failed: {self.database_path}"
            ) from exc

    def count(self) -> int:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT COUNT(*) FROM seen_events").fetchone()
                return int(row[0] if row else 0)
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"durable dedup count failed: {self.database_path}"
            ) from exc

    def compact(self) -> Path | None:
        """Archive rows outside the live window, then remove exactly those rows."""

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                count_row = connection.execute(
                    "SELECT COUNT(*) FROM seen_events"
                ).fetchone()
                excess = max(0, int(count_row[0] if count_row else 0) - self.max_entries)
                if excess == 0:
                    connection.execute("COMMIT")
                    self._writes_since_compaction = 0
                    return None
                rows = connection.execute(
                    """
                    SELECT row_sequence, event_id, seen_at_ms, payload_hash, metadata_json
                    FROM seen_events
                    ORDER BY row_sequence ASC
                    LIMIT ?
                    """,
                    (excess,),
                ).fetchall()
                archive_path = self._write_archive(rows)
                last_sequence = int(rows[-1][0])
                connection.execute(
                    "DELETE FROM seen_events WHERE row_sequence <= ?",
                    (last_sequence,),
                )
                connection.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            raise DurableDedupCorruption(
                f"durable dedup compaction failed: {self.database_path}"
            ) from exc
        self._writes_since_compaction = 0
        return archive_path

    def _write_archive(self, rows: list[tuple[Any, ...]]) -> Path:
        self.archive_directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(
            "\n".join(str(row[1]) for row in rows).encode("utf-8")
        ).hexdigest()[:12]
        while True:
            self._archive_sequence += 1
            name = (
                f"dedup_{time.time_ns()}_{self._archive_sequence:06d}_{digest}.jsonl"
            )
            path = self.archive_directory / name
            try:
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                break
            except FileExistsError:
                continue
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for row_sequence, event_id, seen_at_ms, payload_hash, metadata_json in rows:
                handle.write(
                    json.dumps(
                        {
                            "row_sequence": int(row_sequence),
                            "event_id": str(event_id),
                            "seen_at_ms": int(seen_at_ms),
                            "payload_hash": payload_hash,
                            "metadata": json.loads(metadata_json or "{}"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(self.archive_directory)
        return path


__all__ = [
    "DedupDecision",
    "DurableDedupCorruption",
    "DurableDedupError",
    "DurableEventDedup",
]
