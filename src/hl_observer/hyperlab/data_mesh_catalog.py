"""[Bloc 32 / AUD-278, AUD-324] Catalogue Data Mesh en SQLite + registre de migrations de schema.

- `datasets` : recense chaque artefact persiste (name, venue, etage, path, n_rows, content_hash, ts).
- `schema_migrations` : chaque migration appliquee UNE fois (idempotent), tracee avec sa version+desc.
Timestamps fournis par l'appelant (deterministe/testable). sqlite3 stdlib, 0 reseau.
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence, Tuple

_BOOTSTRAP = [
    ("0001_init", """
        CREATE TABLE IF NOT EXISTS datasets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            venue TEXT,
            etage TEXT NOT NULL,
            path TEXT NOT NULL,
            n_rows INTEGER NOT NULL,
            content_hash TEXT,
            created_ts REAL NOT NULL
        );
    """, "table datasets initiale"),
]


def ouvrir(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
        version TEXT PRIMARY KEY, description TEXT, applied_ts REAL NOT NULL);""")
    conn.commit()
    return conn


def appliquer_migrations(conn: sqlite3.Connection, migrations: Sequence[Tuple[str, str, str]],
                         *, ts: float) -> dict:
    """Applique chaque migration (version, sql, description) UNE seule fois. Idempotent : relancer ne
    reapplique rien. Retourne {appliquees, deja}."""
    deja = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    appliquees = []
    for version, sql, desc in migrations:
        if version in deja:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations(version, description, applied_ts) VALUES(?,?,?)",
                     (version, desc, ts))
        appliquees.append(version)
    conn.commit()
    return {"appliquees": appliquees, "deja": sorted(deja)}


def bootstrap(conn: sqlite3.Connection, *, ts: float) -> dict:
    return appliquer_migrations(conn, _BOOTSTRAP, ts=ts)


def enregistrer_dataset(conn: sqlite3.Connection, *, name: str, etage: str, path: str, n_rows: int,
                        venue: Optional[str] = None, content_hash: Optional[str] = None,
                        ts: float) -> int:
    cur = conn.execute(
        "INSERT INTO datasets(name, venue, etage, path, n_rows, content_hash, created_ts) VALUES(?,?,?,?,?,?,?)",
        (name, venue, etage, path, int(n_rows), content_hash, ts))
    conn.commit()
    return cur.lastrowid


def lister_datasets(conn: sqlite3.Connection, *, etage: Optional[str] = None) -> list:
    q = "SELECT name, venue, etage, path, n_rows, content_hash, created_ts FROM datasets"
    args: tuple = ()
    if etage:
        q += " WHERE etage=?"
        args = (etage,)
    q += " ORDER BY id"
    cols = ("name", "venue", "etage", "path", "n_rows", "content_hash", "created_ts")
    return [dict(zip(cols, row)) for row in conn.execute(q, args)]


def version_schema(conn: sqlite3.Connection) -> list:
    return [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
