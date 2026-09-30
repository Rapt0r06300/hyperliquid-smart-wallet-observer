from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

SQLITE_REPORT_JSON = Path("runtime") / "reports" / "datasets" / "SQLITE_INVENTORY.json"
SQLITE_REPORT_MD = Path("runtime") / "reports" / "datasets" / "SQLITE_INVENTORY.md"

PRIMARY_DATABASES = {
    "runtime/data/hypersmart_simulation_session.sqlite3",
    "data/hl_observer.sqlite3",
}
QUARANTINE_TOKENS = (
    "corrupt",
    "broken",
    "damaged",
    "quarantine",
    "invalid",
)
INTERESTING_TABLES = {
    "fills",
    "positions",
    "position_deltas",
    "wallet_snapshots",
    "wallet_scores",
    "wallet_candidates",
    "wallet_candidate_scores",
    "auto_watchlist",
    "paper_trades",
    "paper_intents",
    "risk_events",
    "raw_events",
    "source_health",
    "collection_runs",
    "leader_snapshots",
    "position_snapshots",
    "open_order_snapshots",
}


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _gib(value: int) -> float:
    return round(int(value) / (1024**3), 4)


def _edge_fingerprint(path: Path, *, edge_bytes: int = 1024 * 1024) -> str:
    """Cheap change detector for very large DB files; explicitly not a full-file hash."""

    size = path.stat().st_size
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(edge_bytes))
        if size > edge_bytes:
            handle.seek(max(0, size - edge_bytes))
            digest.update(handle.read(edge_bytes))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()


def _is_sidecar(path: Path) -> bool:
    lowered = path.name.casefold()
    return lowered.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm"))


def is_quarantined_sqlite_name(path: Path) -> bool:
    lowered = path.name.casefold()
    return any(token in lowered for token in QUARANTINE_TOKENS)


def discover_sqlite_artifacts(root: str | Path) -> list[Path]:
    resolved = Path(root).resolve()
    if not resolved.exists():
        return []
    found: list[Path] = []
    for path in resolved.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.casefold()
        if ".sqlite3" in name or name.endswith((".db", ".db-wal", ".db-shm")):
            found.append(path)
    return sorted(set(found), key=lambda item: item.as_posix().casefold())


def _readonly_uri(path: Path) -> str:
    posix = path.resolve().as_posix()
    return "file:" + quote(posix, safe="/:") + "?mode=ro"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_columns(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"PRAGMA table_xinfo({_quote_identifier(table)})").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        # cid, name, type, notnull, dflt_value, pk, hidden
        result.append(
            {
                "name": str(row[1]),
                "type": str(row[2] or ""),
                "not_null": bool(row[3]),
                "primary_key_order": int(row[5] or 0),
                "hidden": int(row[6] or 0) if len(row) > 6 else 0,
            }
        )
    return result


def _stat1_estimates(connection: sqlite3.Connection) -> dict[str, int]:
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='sqlite_stat1'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return {}
    if not exists:
        return {}
    estimates: dict[str, int] = {}
    try:
        rows = connection.execute("SELECT tbl, stat FROM sqlite_stat1").fetchall()
    except sqlite3.DatabaseError:
        return {}
    for table, stat in rows:
        try:
            first = int(str(stat).split()[0])
        except (TypeError, ValueError, IndexError):
            continue
        name = str(table)
        estimates[name] = max(first, estimates.get(name, 0))
    return estimates


def _sqlite_sequence(connection: sqlite3.Connection) -> dict[str, int]:
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if not exists:
            return {}
        rows = connection.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
    except sqlite3.DatabaseError:
        return {}
    result: dict[str, int] = {}
    for name, seq in rows:
        try:
            result[str(name)] = int(seq)
        except (TypeError, ValueError):
            continue
    return result


def profile_sqlite_database(
    root: str | Path,
    path: str | Path,
    *,
    quick_check: bool = False,
    include_quarantined: bool = False,
) -> dict[str, Any]:
    resolved_root = Path(root).resolve()
    db_path = Path(path).resolve()
    relative = _relative(resolved_root, db_path)
    try:
        size = db_path.stat().st_size
        mtime_ns = db_path.stat().st_mtime_ns
    except OSError as exc:
        return {
            "path": relative,
            "kind": "DATABASE",
            "status": "UNREADABLE_FILE",
            "error": f"{type(exc).__name__}: {exc}",
            "bytes": 0,
        }

    primary = relative.casefold() in {item.casefold() for item in PRIMARY_DATABASES}
    quarantined = is_quarantined_sqlite_name(db_path)
    wal = Path(str(db_path) + "-wal")
    shm = Path(str(db_path) + "-shm")
    base: dict[str, Any] = {
        "path": relative,
        "kind": "DATABASE",
        "role": "PRIMARY" if primary else "SECONDARY",
        "bytes": size,
        "gib": _gib(size),
        "mtime_ns": mtime_ns,
        "wal_present": wal.is_file(),
        "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
        "shm_present": shm.is_file(),
        "shm_bytes": shm.stat().st_size if shm.is_file() else 0,
        "fingerprint": _edge_fingerprint(db_path),
        "fingerprint_method": "EDGE_SHA256_WITH_SIZE",
        "read_only_requested": True,
        "quarantined_by_name": quarantined,
    }
    if quarantined and not include_quarantined:
        return {
            **base,
            "status": "QUARANTINED_NAME",
            "opened": False,
            "reason": "Le nom indique une ancienne base corrompue/endommagee; ouverture automatique refusee.",
        }

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=2.0)
        connection.execute("PRAGMA query_only=ON")
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE type IN ('table','index','view','trigger') ORDER BY type, name"
        ).fetchall()
        stat1 = _stat1_estimates(connection)
        sequence = _sqlite_sequence(connection)
        table_names = [str(row[1]) for row in schema_rows if str(row[0]) == "table"]
        index_counts: Counter[str] = Counter(
            str(row[2]) for row in schema_rows if str(row[0]) == "index"
        )
        tables: list[dict[str, Any]] = []
        for table in table_names:
            columns = _table_columns(connection, table)
            tables.append(
                {
                    "name": table,
                    "column_count": len(columns),
                    "columns": columns,
                    "index_count": int(index_counts.get(table, 0)),
                    "sqlite_stat1_row_estimate": stat1.get(table),
                    "autoincrement_last_sequence": sequence.get(table),
                    "interesting_for_hypersmart": table.casefold() in INTERESTING_TABLES,
                }
            )
        quick_result: str | None = None
        if quick_check:
            row = connection.execute("PRAGMA quick_check(1)").fetchone()
            quick_result = str(row[0]) if row else None
        interesting = sorted(
            table for table in table_names if table.casefold() in INTERESTING_TABLES
        )
        return {
            **base,
            "status": "READABLE_READ_ONLY",
            "opened": True,
            "sqlite": {
                "page_size": page_size,
                "page_count": page_count,
                "freelist_count": freelist_count,
                "database_bytes_from_pages": page_size * page_count,
                "schema_version": schema_version,
                "user_version": user_version,
                "journal_mode_observed": journal_mode,
                "quick_check": quick_result,
            },
            "schema": {
                "table_count": len(table_names),
                "index_count": sum(1 for row in schema_rows if str(row[0]) == "index"),
                "view_count": sum(1 for row in schema_rows if str(row[0]) == "view"),
                "trigger_count": sum(1 for row in schema_rows if str(row[0]) == "trigger"),
                "interesting_tables": interesting,
                "tables": tables,
            },
            "economic_research_candidate": bool(interesting),
        }
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        return {
            **base,
            "status": "UNREADABLE_DATABASE",
            "opened": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if connection is not None:
            connection.close()


def profile_sqlite_workspace(
    root: str | Path,
    *,
    quick_check: bool = False,
    include_quarantined: bool = False,
) -> dict[str, Any]:
    resolved = Path(root).resolve()
    artifacts = discover_sqlite_artifacts(resolved)
    databases: list[dict[str, Any]] = []
    sidecars: list[dict[str, Any]] = []
    for path in artifacts:
        if _is_sidecar(path):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            sidecars.append(
                {
                    "path": _relative(resolved, path),
                    "kind": "SIDECAR",
                    "bytes": size,
                    "gib": _gib(size),
                }
            )
            continue
        # A .sqlite3.corrupted-* file is deliberately reported/quarantined too.
        if ".sqlite3" not in path.name.casefold() and not path.name.casefold().endswith(".db"):
            continue
        databases.append(
            profile_sqlite_database(
                resolved,
                path,
                quick_check=quick_check,
                include_quarantined=include_quarantined,
            )
        )

    status_counts = Counter(str(item.get("status") or "UNKNOWN") for item in databases)
    total_db_bytes = sum(int(item.get("bytes") or 0) for item in databases)
    readable_bytes = sum(
        int(item.get("bytes") or 0)
        for item in databases
        if item.get("status") == "READABLE_READ_ONLY"
    )
    interesting = [
        item for item in databases if item.get("economic_research_candidate") is True
    ]
    return {
        "schema": "hypersmart.sqlite_workspace_inventory.v1",
        "root": str(resolved),
        "read_only": True,
        "row_values_exported": False,
        "quick_check_requested": bool(quick_check),
        "database_count": len(databases),
        "database_bytes": total_db_bytes,
        "database_gib": _gib(total_db_bytes),
        "readable_database_count": int(status_counts.get("READABLE_READ_ONLY", 0)),
        "readable_database_bytes": readable_bytes,
        "readable_database_gib": _gib(readable_bytes),
        "quarantined_database_count": int(status_counts.get("QUARANTINED_NAME", 0)),
        "unreadable_database_count": int(status_counts.get("UNREADABLE_DATABASE", 0))
        + int(status_counts.get("UNREADABLE_FILE", 0)),
        "economic_research_candidate_count": len(interesting),
        "sidecar_count": len(sidecars),
        "sidecar_bytes": sum(int(item.get("bytes") or 0) for item in sidecars),
        "status_counts": dict(status_counts),
        "databases": databases,
        "sidecars": sidecars,
    }


def render_sqlite_markdown(profile: Mapping[str, Any]) -> str:
    lines = [
        "# Inventaire SQLite FULL/COLD",
        "",
        "- Ouverture des bases : **lecture seule (`mode=ro`)**.",
        "- Les fichiers dont le nom indique `corrupt/broken/damaged/quarantine/invalid` sont refusés automatiquement.",
        "- Les WAL/SHM sont inventoriés mais ne sont jamais ouverts comme bases.",
        "- Aucune valeur de ligne n'est exportée dans ce rapport.",
        f"- Bases repérées : **{profile.get('database_count', 0)}** ({profile.get('database_gib', 0)} Gio).",
        f"- Bases lisibles en lecture seule : **{profile.get('readable_database_count', 0)}** ({profile.get('readable_database_gib', 0)} Gio).",
        f"- Bases mises en quarantaine par leur nom : **{profile.get('quarantined_database_count', 0)}**.",
        f"- Bases avec tables utiles à la recherche : **{profile.get('economic_research_candidate_count', 0)}**.",
        "",
        "| Base | Rôle | Gio | État | Tables | Tables HyperSmart utiles | WAL |",
        "|---|---|---:|---|---:|---|---|",
    ]
    raw_databases = profile.get("databases")
    databases = raw_databases if isinstance(raw_databases, list) else []
    for item in databases:
        if not isinstance(item, Mapping):
            continue
        schema = item.get("schema") if isinstance(item.get("schema"), Mapping) else {}
        useful = schema.get("interesting_tables") if isinstance(schema, Mapping) else []
        useful_text = ", ".join(str(value) for value in useful[:12]) if isinstance(useful, list) else ""
        lines.append(
            f"| `{item.get('path')}` | {item.get('role', '')} | {item.get('gib', 0)} | "
            f"{item.get('status')} | {schema.get('table_count', 0) if isinstance(schema, Mapping) else 0} | "
            f"{useful_text or '-'} | {'oui' if item.get('wal_present') else 'non'} |"
        )
    lines.extend(
        [
            "",
            "> Un inventaire lisible ne prouve pas encore qu'une table contient un edge. Il prouve seulement que la base peut être exploitée sans mutation et quelles structures historiques sont disponibles.",
            "",
        ]
    )
    return "\n".join(lines)


def write_sqlite_inventory(
    root: str | Path,
    *,
    quick_check: bool = False,
    include_quarantined: bool = False,
) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    profile = profile_sqlite_workspace(
        resolved,
        quick_check=quick_check,
        include_quarantined=include_quarantined,
    )
    json_path = resolved / SQLITE_REPORT_JSON
    md_path = resolved / SQLITE_REPORT_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_sqlite_markdown(profile), encoding="utf-8")
    return json_path, md_path, profile


__all__ = [
    "PRIMARY_DATABASES",
    "SQLITE_REPORT_JSON",
    "SQLITE_REPORT_MD",
    "discover_sqlite_artifacts",
    "is_quarantined_sqlite_name",
    "profile_sqlite_database",
    "profile_sqlite_workspace",
    "render_sqlite_markdown",
    "write_sqlite_inventory",
]
