from __future__ import annotations

import sqlite3
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "6"


def get_db_path(config: AppConfig) -> Path:
    return Path(config.database_path)


def initialize_database(config: AppConfig) -> Path:
    db_path = get_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection(config) as conn:
        conn.executescript(schema)
        _ensure_sprint3_columns(conn)
        _ensure_sprint4_columns(conn)
        conn.execute(
            "INSERT OR REPLACE INTO app_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
    return db_path


def get_connection(config: AppConfig) -> sqlite3.Connection:
    db_path = get_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_sprint3_columns(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "fills", "closed_pnl", "REAL")
    _ensure_column(conn, "fills", "action_type", "TEXT")
    _ensure_column(conn, "fills", "start_position", "REAL")
    _ensure_column(conn, "fills", "fee_token", "TEXT")
    _ensure_column(conn, "fills", "raw_json", "TEXT")
    score_columns = {
        "status": "TEXT",
        "usable_fills": "INTEGER",
        "skipped_fills": "INTEGER",
        "first_fill_at": "TEXT",
        "last_fill_at": "TEXT",
        "history_days": "REAL",
        "gross_pnl": "REAL",
        "net_pnl": "REAL",
        "total_fees": "REAL",
        "average_win": "REAL",
        "average_loss": "REAL",
        "sample_quality_score": "REAL",
        "recency_score": "REAL",
        "consistency_score": "REAL",
        "risk_score": "REAL",
        "warnings_json": "TEXT",
    }
    for column, definition in score_columns.items():
        _ensure_column(conn, "wallet_scores", column, definition)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_scores_status ON wallet_scores(status)")


def _ensure_sprint4_columns(conn: sqlite3.Connection) -> None:
    trade_columns = {
        "intent_id": "TEXT",
        "wallet_address": "TEXT",
        "notional": "REAL",
        "fee_entry": "REAL",
        "fee_exit": "REAL",
        "slippage_entry": "REAL",
        "slippage_exit": "REAL",
        "spread_cost": "REAL",
        "gross_pnl": "REAL",
        "net_pnl": "REAL",
        "status": "TEXT",
        "close_reason": "TEXT",
        "warnings_json": "TEXT",
    }
    for column, definition in trade_columns.items():
        _ensure_column(conn, "paper_trades", column, definition)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_wallet ON paper_trades(wallet_address)")
    _ensure_copy_mode_columns(conn)


def _ensure_copy_mode_columns(conn: sqlite3.Connection) -> None:
    for column, definition in {
        "source_snapshot_id": "TEXT",
        "collection_run_id": "TEXT",
    }.items():
        _ensure_column(conn, "copy_signal_candidates", column, definition)
    for column, definition in {
        "risk_level": "TEXT NOT NULL DEFAULT 'INFO'",
        "component": "TEXT NOT NULL DEFAULT 'copy_mode'",
    }.items():
        _ensure_column(conn, "no_trade_decisions", column, definition)
    _ensure_column(conn, "collection_runs", "stopped_reason", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
