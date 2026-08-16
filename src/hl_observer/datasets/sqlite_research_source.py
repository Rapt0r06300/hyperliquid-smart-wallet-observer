from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote

from hl_observer.datasets.sqlite_profiler import (
    discover_sqlite_artifacts,
    is_quarantined_sqlite_name,
)

SAFE_RESEARCH_COLUMNS: dict[str, tuple[str, ...]] = {
    "fills": (
        "id",
        "wallet_address",
        "coin",
        "exchange_ts",
        "side",
        "price",
        "size",
        "fill_hash",
        "oid",
        "tid",
        "direction",
        "start_position",
        "closed_pnl",
        "fee",
        "created_at",
    ),
    "positions": (
        "id",
        "wallet_address",
        "coin",
        "side",
        "size",
        "entry_price",
        "entry_px_estimated",
        "last_px",
        "notional_usdc",
        "source",
        "confidence_score",
        "opened_at_ms",
        "updated_at_ms",
        "status",
        "created_at",
    ),
    "position_deltas": (
        "id",
        "wallet_address",
        "coin",
        "previous_side",
        "new_side",
        "previous_size",
        "current_size",
        "new_size",
        "delta_size",
        "delta_notional_usdc",
        "action",
        "exchange_ts",
        "fill_id",
        "source_event_id",
        "side",
        "price",
        "fill_size",
        "delta_type",
        "confidence",
        "confidence_score",
        "detected_at_ms",
        "source",
        "snapshot_id",
        "is_paper_eligible",
        "delta_hash",
        "created_at",
    ),
    "wallet_snapshots": (
        "id",
        "wallet_address",
        "collection_run_id",
        "local_received_ts",
        "exchange_ts",
        "source",
        "stopped_reason",
        "summary",
        "created_at",
    ),
    "wallet_scores": (
        "id",
        "wallet_address",
        "score",
        "decision",
        "created_at",
    ),
    "wallet_candidates": (
        "id",
        "run_id",
        "address",
        "coin",
        "source_name",
        "source_type",
        "label",
        "external_pnl_usdc",
        "external_roi_pct",
        "external_volume_usdc",
        "external_win_rate",
        "external_position_usdc",
        "external_unrealized_pnl",
        "external_funding_fee",
        "first_seen_ms",
        "last_seen_ms",
        "confidence_score",
        "selected_for_backfill",
        "rejection_reason",
    ),
    "wallet_candidate_scores": (
        "id",
        "wallet_address",
        "coin",
        "run_id",
        "pnl_positive_score",
        "roi_positive_score",
        "activity_score",
        "recency_score",
        "size_score",
        "copyability_pre_score",
        "source_confidence_score",
        "final_discovery_score",
        "decision",
    ),
    "paper_trades": (
        "id",
        "family",
        "coin",
        "side",
        "status",
        "notional_usd",
        "entry_price",
        "exit_price",
        "gross_pnl_usd",
        "net_pnl_usd",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
        "opened_at_ms",
        "closed_at_ms",
        "created_at",
    ),
    "paper_intents": (
        "id",
        "family",
        "coin",
        "side",
        "status",
        "notional_usd",
        "reference_price",
        "created_at_ms",
        "created_at",
    ),
    "risk_events": (
        "id",
        "family",
        "coin",
        "reason",
        "decision",
        "severity",
        "created_at_ms",
        "created_at",
    ),
    "source_health": (
        "source_name",
        "last_event_at_ms",
        "last_success_at_ms",
        "seconds_since_last_event",
        "observed_latency_ms",
        "freshness_status",
        "is_consistent",
        "is_heartbeat",
        "error_message",
        "created_at",
    ),
}


def _readonly_uri(path: Path) -> str:
    return "file:" + quote(path.resolve().as_posix(), safe="/:") + "?mode=ro"


def _open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_readonly_uri(path), uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _is_sidecar(path: Path) -> bool:
    lowered = path.name.casefold()
    return lowered.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm"))


def safe_sqlite_databases(root: str | Path) -> list[Path]:
    resolved = Path(root).resolve()
    result: list[Path] = []
    for path in discover_sqlite_artifacts(resolved):
        if _is_sidecar(path) or is_quarantined_sqlite_name(path):
            continue
        lowered = path.name.casefold()
        if not (lowered.endswith(".sqlite3") or lowered.endswith(".db")):
            continue
        result.append(path)
    return sorted(set(result), key=lambda item: item.as_posix().casefold())


def _schema_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    escaped = table.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_xinfo("{escaped}")').fetchall()
    return tuple(str(row[1]) for row in rows)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        ).fetchall()
    }


def build_sqlite_research_catalog(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    databases: list[dict[str, Any]] = []
    table_sources: dict[str, list[str]] = {name: [] for name in SAFE_RESEARCH_COLUMNS}
    for path in safe_sqlite_databases(resolved):
        try:
            connection = _open_readonly(path)
        except sqlite3.DatabaseError as exc:
            databases.append(
                {
                    "path": str(path),
                    "status": "UNREADABLE",
                    "error": f"{type(exc).__name__}: {exc}",
                    "tables": [],
                }
            )
            continue
        try:
            names = _table_names(connection)
            allowed = sorted(names & set(SAFE_RESEARCH_COLUMNS))
            table_rows: list[dict[str, Any]] = []
            for table in allowed:
                existing = _schema_columns(connection, table)
                selected = tuple(
                    column for column in SAFE_RESEARCH_COLUMNS[table] if column in existing
                )
                max_rowid: int | None = None
                try:
                    quoted = '"' + table.replace('"', '""') + '"'
                    row = connection.execute(f"SELECT MAX(rowid) FROM {quoted}").fetchone()
                    if row and row[0] is not None:
                        max_rowid = int(row[0])
                except (sqlite3.DatabaseError, TypeError, ValueError):
                    max_rowid = None
                table_rows.append(
                    {
                        "name": table,
                        "safe_columns": list(selected),
                        "safe_column_count": len(selected),
                        "max_rowid_upper_bound": max_rowid,
                    }
                )
                table_sources[table].append(str(path))
            databases.append(
                {
                    "path": str(path),
                    "status": "READABLE_READ_ONLY",
                    "tables": table_rows,
                }
            )
        finally:
            connection.close()
    return {
        "schema": "hypersmart.sqlite_research_catalog.v1",
        "root": str(resolved),
        "read_only": True,
        "safe_columns_only": True,
        "raw_json_columns_excluded": True,
        "database_count": len(databases),
        "readable_database_count": sum(
            1 for item in databases if item.get("status") == "READABLE_READ_ONLY"
        ),
        "table_sources": {key: value for key, value in table_sources.items() if value},
        "databases": databases,
    }


def iter_research_rows(
    root: str | Path,
    table: str,
    *,
    limit: int = 0,
    batch_size: int = 2_000,
) -> Iterator[dict[str, Any]]:
    """Stream safe economic columns across every readable historical SQLite DB.

    The caller chooses a table from the fixed allowlist. Raw JSON/payload columns are
    intentionally excluded. No UPDATE/INSERT/DELETE statement can be constructed here.
    """

    if table not in SAFE_RESEARCH_COLUMNS:
        raise ValueError(f"Table non autorisée pour la recherche SQLite: {table}")
    resolved = Path(root).resolve()
    emitted = 0
    for database in safe_sqlite_databases(resolved):
        connection: sqlite3.Connection | None = None
        try:
            connection = _open_readonly(database)
            if table not in _table_names(connection):
                continue
            existing = _schema_columns(connection, table)
            columns = [column for column in SAFE_RESEARCH_COLUMNS[table] if column in existing]
            if not columns:
                continue
            quoted_table = '"' + table.replace('"', '""') + '"'
            quoted_columns = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
            cursor = connection.execute(f"SELECT {quoted_columns} FROM {quoted_table}")
            while True:
                rows = cursor.fetchmany(max(1, int(batch_size)))
                if not rows:
                    break
                for row in rows:
                    payload = {column: row[column] for column in columns}
                    payload["_source_database"] = str(database)
                    yield payload
                    emitted += 1
                    if limit > 0 and emitted >= limit:
                        return
        except sqlite3.DatabaseError:
            continue
        finally:
            if connection is not None:
                connection.close()


def stream_table_to_jsonl(
    root: str | Path,
    table: str,
    output: str | Path,
    *,
    limit: int = 0,
    batch_size: int = 2_000,
) -> dict[str, Any]:
    """Optional local derived view; sources remain untouched and output is explicit."""

    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    rows = 0
    import json

    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for payload in iter_research_rows(
            root,
            table,
            limit=limit,
            batch_size=batch_size,
        ):
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            rows += 1
    temporary.replace(target)
    return {
        "table": table,
        "rows": rows,
        "output": str(target),
        "read_only_sources": True,
        "safe_columns_only": True,
    }


__all__ = [
    "SAFE_RESEARCH_COLUMNS",
    "build_sqlite_research_catalog",
    "iter_research_rows",
    "safe_sqlite_databases",
    "stream_table_to_jsonl",
]
