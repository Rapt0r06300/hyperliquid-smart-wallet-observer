"""Anti-bloat au SINK: store_raw_event no-op si HYPERSMART_DISABLE_RAW_STORAGE=1.

Couvre TOUS les appelants (scanner de marche inclus, qui bypassait le flag settings
et gonflait la DB). Régression du crash 29 Go.
"""

from __future__ import annotations

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.repositories import CollectionRepository


def _repo(tmp_path):
    url = f"sqlite:///{tmp_path}/raw.sqlite3"
    init_db(url)
    sf = create_session_factory(create_sqlite_engine(url))
    return sf


def test_raw_event_written_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_DISABLE_RAW_STORAGE", raising=False)
    sf = _repo(tmp_path)
    with sf() as s:
        repo = CollectionRepository(s)
        ev = repo.store_raw_event(source="hl", endpoint="/info", request_type="meta",
                                  request_payload={"a": 1}, response_payload={"b": 2})
        assert ev is not None                       # écrit par défaut


def test_raw_event_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_DISABLE_RAW_STORAGE", "1")
    sf = _repo(tmp_path)
    with sf() as s:
        repo = CollectionRepository(s)
        ev = repo.store_raw_event(source="hl", endpoint="/info", request_type="l2Book",
                                  request_payload={"coin": "BTC"}, response_payload={"levels": [1, 2, 3]})
        assert ev is None                           # coupé au sink -> aucun event
