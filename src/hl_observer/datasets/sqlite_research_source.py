from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from hl_observer.datasets.sqlite_profiler import (
    discover_sqlite_artifacts,
    is_quarantined_sqlite_name,
)

SAFE_RESEARCH_COLUMNS: dict[str, tuple[str, ...]] = {
    "fills": (
        "id", "wallet_address", "coin", "exchange_ts", "side", "price", "size",
        "fill_hash", "oid", "tid", "direction", "start_position", "closed_pnl", "fee", "created_at",
    ),
    "positions": (
        "id", "wallet_address", "coin", "side", "size", "entry_price", "entry_px_estimated",
        "last_px", "notional_usdc", "source", "confidence_score", "opened_at_ms", "updated_at_ms",
        "status", "created_at",
    ),
    "position_deltas": (
        "id", "wallet_address", "coin", "previous_side", "new_side", "previous_size", "current_size",
        "new_size", "delta_size", "delta_notional_usdc", "action", "exchange_ts", "fill_id",
        "source_event_id", "side", "price", "fill_size", "delta_type", "confidence", "confidence_score",
        "detected_at_ms", "source", "snapshot_id", "is_paper_eligible", "delta_hash", "created_at",
    ),
    "wallet_snapshots": (
        "id", "wallet_address", "collection_run_id", "local_received_ts", "exchange_ts", "source",
        "stopped_reason", "summary", "created_at",
    ),
    "wallet_scores": (
        "id", "wallet_address", "score", "decision", "created_at",
    ),
    "wallet_candidates": (
        "id", "run_id", "address", "coin", "source_name", "source_type", "label",
        "external_pnl_usdc", "external_roi_pct", "external_volume_usdc", "external_win_rate",
        "external_position_usdc", "external_unrealized_pnl", "external_funding_fee", "first_seen_ms",
        "last_seen_ms", "confidence_score", "selected_for_backfill", "rejection_reason",
    ),
    "wallet_candidate_scores": (
        "id", "wallet_address", "coin", "run_id", "pnl_positive_score", "roi_positive_score",
        "activity_score", "recency_score", "size_score", "copyability_pre_score", "source_confidence_score",
        "final_discovery_score", "decision",
    ),
    "paper_trades": (
        "id", "family", "coin", "side", "status", "notional_usd", "entry_price", "exit_price",
        "gross_pnl_usd", "net_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
        "latency_cost_usd", "opened_at_ms", "closed_at_ms", "created_at",
    ),
    "paper_intents": (
        "id", "family", "coin", "side", "status", "notional_usd", "reference_price", "created_at_ms", "created_at",
    ),
    "risk_events": (
        "id", "family", "coin", "reason", "decision", "severity", "created_at_ms", "created_at",
    ),
    "source_health": (
        "source_name", "last_event_at_ms", "last_success_at_ms", "seconds_since_last_event",
        "observed_latency_ms", "freshness_status", "is_consistent", "is_heartbeat", "error_message", "created_at",
    ),
}

TIME_FILTER_COLUMN: dict[str, str] = {
    "fills": "exchange_ts",
    "positions": "updated_at_ms",
    "position_deltas": "exchange_ts",
    "wallet_snapshots": "local_received_ts",
    "wallet_candidates": "last_seen_ms",
    "paper_trades": "opened_at_ms",
    "paper_intents": "created_at_ms",
    "risk_events": "created_at_ms",
    "source_health": "last_event_at_ms",
}
WALLET_FILTER_COLUMN: dict[str, str] = {
    "fills": "wallet_address",
    "positions": "wallet_address",
    "position_deltas": "wallet_address",
    "wallet_snapshots": "wallet_address",
    "wallet_scores": "wallet_address",
    "wallet_candidates": "address",
    "wallet_candidate_scores": "wallet_address",
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


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


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
                selected = tuple(column for column in SAFE_RESEARCH_COLUMNS[table] if column in existing)
                max_rowid: int | None = None
                try:
                    row = connection.execute(f"SELECT MAX(rowid) FROM {_quoted(table)}").fetchone()
                    if row and row[0] is not None:
                        max_rowid = int(row[0])
                except (sqlite3.DatabaseError, TypeError, ValueError):
                    max_rowid = None
                time_column = TIME_FILTER_COLUMN.get(table)
                wallet_column = WALLET_FILTER_COLUMN.get(table)
                table_rows.append(
                    {
                        "name": table,
                        "safe_columns": list(selected),
                        "safe_column_count": len(selected),
                        "max_rowid_upper_bound": max_rowid,
                        "time_filter_column": time_column if time_column in existing else None,
                        "coin_filter_supported": "coin" in existing,
                        "wallet_filter_column": wallet_column if wallet_column in existing else None,
                        "family_filter_supported": "family" in existing,
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
        "schema": "hypersmart.sqlite_research_catalog.v2",
        "root": str(resolved),
        "read_only": True,
        "safe_columns_only": True,
        "raw_json_columns_excluded": True,
        "database_count": len(databases),
        "readable_database_count": sum(1 for item in databases if item.get("status") == "READABLE_READ_ONLY"),
        "table_sources": {key: value for key, value in table_sources.items() if value},
        "databases": databases,
    }


def _validate_filters(
    table: str,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> None:
    if start_ms is not None and end_ms is not None and int(start_ms) > int(end_ms):
        raise ValueError("start_ms doit être inférieur ou égal à end_ms")
    if (start_ms is not None or end_ms is not None) and table not in TIME_FILTER_COLUMN:
        raise ValueError(f"La table {table} n'a pas de colonne temporelle milliseconde autorisée")


def iter_research_rows(
    root: str | Path,
    table: str,
    *,
    limit: int = 0,
    batch_size: int = 2_000,
    start_ms: int | None = None,
    end_ms: int | None = None,
    coin: str | None = None,
    wallet: str | None = None,
    family: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream safe economic columns with optional causal selection filters.

    Every identifier comes from a fixed allowlist. Filter values are passed as SQL
    parameters. Raw JSON/payload columns are excluded and source DBs are read-only.
    """

    if table not in SAFE_RESEARCH_COLUMNS:
        raise ValueError(f"Table non autorisée pour la recherche SQLite: {table}")
    _validate_filters(table, start_ms=start_ms, end_ms=end_ms)
    resolved = Path(root).resolve()
    emitted = 0
    normalized_coin = str(coin).strip().upper() if coin else None
    normalized_wallet = str(wallet).strip() if wallet else None
    normalized_family = str(family).strip() if family else None

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
            time_column = TIME_FILTER_COLUMN.get(table)
            wallet_column = WALLET_FILTER_COLUMN.get(table)
            if (start_ms is not None or end_ms is not None) and time_column not in existing:
                continue
            if normalized_coin and "coin" not in existing:
                continue
            if normalized_wallet and wallet_column not in existing:
                continue
            if normalized_family and "family" not in existing:
                continue

            predicates: list[str] = []
            parameters: list[Any] = []
            if start_ms is not None and time_column:
                predicates.append(f"{_quoted(time_column)} >= ?")
                parameters.append(int(start_ms))
            if end_ms is not None and time_column:
                predicates.append(f"{_quoted(time_column)} <= ?")
                parameters.append(int(end_ms))
            if normalized_coin:
                predicates.append("UPPER(coin) = ?")
                parameters.append(normalized_coin)
            if normalized_wallet and wallet_column:
                predicates.append(f"{_quoted(wallet_column)} = ?")
                parameters.append(normalized_wallet)
            if normalized_family:
                predicates.append("family = ?")
                parameters.append(normalized_family)

            sql = f"SELECT {', '.join(_quoted(column) for column in columns)} FROM {_quoted(table)}"
            if predicates:
                sql += " WHERE " + " AND ".join(predicates)
            if time_column and time_column in existing:
                sql += f" ORDER BY {_quoted(time_column)} ASC"
            cursor = connection.execute(sql, parameters)
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
    start_ms: int | None = None,
    end_ms: int | None = None,
    coin: str | None = None,
    wallet: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    """Write an explicit local derived view; the SQLite sources remain untouched."""

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
            start_ms=start_ms,
            end_ms=end_ms,
            coin=coin,
            wallet=wallet,
            family=family,
        ):
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            rows += 1
    temporary.replace(target)
    return {
        "table": table,
        "rows": rows,
        "output": str(target),
        "filters": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "coin": coin,
            "wallet": wallet,
            "family": family,
        },
        "read_only_sources": True,
        "safe_columns_only": True,
    }


__all__ = [
    "SAFE_RESEARCH_COLUMNS",
    "TIME_FILTER_COLUMN",
    "WALLET_FILTER_COLUMN",
    "build_sqlite_research_catalog",
    "iter_research_rows",
    "safe_sqlite_databases",
    "stream_table_to_jsonl",
]
