from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_sqlite_engine(database_url: str = "sqlite:///./data/hl_observer.sqlite3") -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connect_args = {"timeout": 30}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        _configure_sqlite_runtime(engine)
    return engine


def _configure_sqlite_runtime(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(database_url: str = "sqlite:///./data/hl_observer.sqlite3") -> None:
    from hl_observer.storage import models  # noqa: F401

    engine = create_sqlite_engine(database_url)
    Base.metadata.create_all(engine)
    _apply_sqlite_compat_migrations(engine)


def _apply_sqlite_compat_migrations(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "raw_events" not in table_names:
        return
    existing = {column["name"] for column in inspector.get_columns("raw_events")}
    missing_columns = {
        "endpoint": "VARCHAR(128)",
        "request_type": "VARCHAR(64)",
        "wallet_address": "VARCHAR(64)",
        "request_payload_json": "JSON",
        "response_payload_json": "JSON",
        "response_hash": "VARCHAR(64)",
        "fetched_at_ms": "INTEGER",
        "success": "BOOLEAN",
        "error_message": "TEXT",
    }
    with engine.begin() as connection:
        for column_name, column_type in missing_columns.items():
            if column_name not in existing:
                connection.execute(
                    text(f"ALTER TABLE raw_events ADD COLUMN {column_name} {column_type}")
                )
    if "fills" in table_names:
        fill_existing = {column["name"] for column in inspector.get_columns("fills")}
        fill_missing_columns = {
            "fill_hash": "VARCHAR(64)",
            "oid": "VARCHAR(128)",
            "tid": "VARCHAR(128)",
            "direction": "VARCHAR(64)",
            "start_position": "FLOAT",
            "closed_pnl": "FLOAT",
            "fee": "FLOAT",
        }
        with engine.begin() as connection:
            for column_name, column_type in fill_missing_columns.items():
                if column_name not in fill_existing:
                    connection.execute(
                        text(f"ALTER TABLE fills ADD COLUMN {column_name} {column_type}")
                    )
    if "position_deltas" in table_names:
        delta_existing = {column["name"] for column in inspector.get_columns("position_deltas")}
        delta_missing_columns = {
            "previous_side": "VARCHAR(16)",
            "new_side": "VARCHAR(16)",
            "new_size": "FLOAT DEFAULT 0.0",
            "delta_notional_usdc": "FLOAT",
            "action": "VARCHAR(32) DEFAULT 'UNKNOWN'",
            "fill_id": "INTEGER",
            "source_event_id": "INTEGER",
            "side": "VARCHAR(16)",
            "price": "FLOAT",
            "fill_size": "FLOAT",
            "delta_type": "VARCHAR(64) DEFAULT 'unknown'",
            "confidence": "VARCHAR(32) DEFAULT 'medium'",
            "confidence_score": "FLOAT DEFAULT 0.0",
            "detected_at_ms": "INTEGER",
            "source": "VARCHAR(64) DEFAULT 'fills'",
            "delta_hash": "VARCHAR(64)",
            "raw_json": "JSON",
        }
        with engine.begin() as connection:
            for column_name, column_type in delta_missing_columns.items():
                if column_name not in delta_existing:
                    connection.execute(
                        text(f"ALTER TABLE position_deltas ADD COLUMN {column_name} {column_type}")
                    )
    if "positions" in table_names:
        position_existing = {column["name"] for column in inspector.get_columns("positions")}
        position_missing_columns = {
            "side": "VARCHAR(16)",
            "entry_px_estimated": "FLOAT",
            "last_px": "FLOAT",
            "notional_usdc": "FLOAT",
            "source": "VARCHAR(64) DEFAULT 'fills'",
            "confidence_score": "FLOAT DEFAULT 0.0",
            "opened_at_ms": "INTEGER",
            "updated_at_ms": "INTEGER",
            "status": "VARCHAR(32) DEFAULT 'INCOMPLETE'",
        }
        with engine.begin() as connection:
            for column_name, column_type in position_missing_columns.items():
                if column_name not in position_existing:
                    connection.execute(
                        text(f"ALTER TABLE positions ADD COLUMN {column_name} {column_type}")
                    )
    for table_name in ("wallet_candidates", "auto_watchlist", "wallet_candidate_scores"):
        if table_name in table_names:
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "coin" not in existing_columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN coin VARCHAR(32)"))
