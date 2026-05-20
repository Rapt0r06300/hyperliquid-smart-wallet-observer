from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_sqlite_engine(database_url: str = "sqlite:///./logs/hl_observer.sqlite3") -> Engine:
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(database_url: str = "sqlite:///./logs/hl_observer.sqlite3") -> None:
    from hl_observer.storage import models  # noqa: F401

    engine = create_sqlite_engine(database_url)
    Base.metadata.create_all(engine)
