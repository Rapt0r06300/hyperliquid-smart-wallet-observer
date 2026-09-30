"""SQLite-backed RawStore (V12 capability E - persistence + dedupe).

Same contract as the in-memory ``RawStore`` (put/get/count/recent/contexts) but
persisted to SQLite, so raw provenance survives restarts. Dedupe is enforced at the
DB level by a PRIMARY KEY on ``(context, raw_hash)``: replaying a backfill adds zero
duplicate rows, and LIVE / BACKTEST / REPLAY / TEST_FIXTURE never mix (context is part
of the key). Read-only research storage: records real fetched payloads, never an order.
"""

from __future__ import annotations

import json
import sqlite3

from hl_observer.storage.raw_store import RawEvent
from hl_observer.storage.run_context import RunContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    context        TEXT NOT NULL,
    raw_hash       TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    kind           TEXT NOT NULL,
    fetched_at_ms  INTEGER NOT NULL,
    parsed_hash    TEXT,
    source_ts_ms   INTEGER,
    item_count     INTEGER,
    request_id     TEXT,
    payload        TEXT,
    PRIMARY KEY (context, raw_hash)
);
CREATE INDEX IF NOT EXISTS idx_raw_events_src ON raw_events (context, source_id, fetched_at_ms);
"""


def _ctx(value) -> RunContext:
    return value if isinstance(value, RunContext) else RunContext(str(value).upper())


class SqliteRawStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def put(self, event: RawEvent) -> bool:
        """Insert one raw event. Returns False if it's a duplicate (same context+hash)."""
        try:
            payload = json.dumps(event.payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            payload = json.dumps(repr(event.payload))
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO raw_events "
            "(context, raw_hash, source_id, kind, fetched_at_ms, parsed_hash, source_ts_ms, item_count, request_id, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event.context.value, event.raw_hash, event.source_id, event.kind,
                int(event.fetched_at_ms), event.parsed_hash, event.source_ts_ms,
                event.item_count, event.request_id, payload,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0  # 0 when the row already existed (deduped)

    def _row_to_event(self, row: sqlite3.Row) -> RawEvent:
        try:
            payload = json.loads(row["payload"]) if row["payload"] is not None else None
        except (TypeError, ValueError):
            payload = None
        return RawEvent(
            source_id=row["source_id"], kind=row["kind"], raw_hash=row["raw_hash"],
            fetched_at_ms=row["fetched_at_ms"], context=_ctx(row["context"]),
            parsed_hash=row["parsed_hash"], source_ts_ms=row["source_ts_ms"],
            item_count=row["item_count"], request_id=row["request_id"], payload=payload,
        )

    def get(self, raw_hash: str, *, context: RunContext = RunContext.LIVE) -> RawEvent | None:
        row = self._conn.execute(
            "SELECT * FROM raw_events WHERE context=? AND raw_hash=?",
            (_ctx(context).value, raw_hash),
        ).fetchone()
        return self._row_to_event(row) if row else None

    def count(self, *, context: RunContext | None = None) -> int:
        if context is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM raw_events WHERE context=?", (_ctx(context).value,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM raw_events").fetchone()
        return int(row["n"])

    def recent(self, *, source_id: str | None = None, context: RunContext = RunContext.LIVE, limit: int = 50) -> list[RawEvent]:
        if source_id is None:
            rows = self._conn.execute(
                "SELECT * FROM raw_events WHERE context=? ORDER BY fetched_at_ms DESC, rowid DESC LIMIT ?",
                (_ctx(context).value, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM raw_events WHERE context=? AND source_id=? ORDER BY fetched_at_ms DESC, rowid DESC LIMIT ?",
                (_ctx(context).value, source_id, int(limit)),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def contexts(self) -> list[RunContext]:
        rows = self._conn.execute("SELECT DISTINCT context FROM raw_events").fetchall()
        return [_ctx(r["context"]) for r in rows]

    def close(self) -> None:
        self._conn.close()


__all__ = ["SqliteRawStore"]
