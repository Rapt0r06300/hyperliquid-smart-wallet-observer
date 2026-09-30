from hl_observer.storage.raw_store import make_raw_event
from hl_observer.storage.raw_store_sqlite import SqliteRawStore
from hl_observer.storage.run_context import RunContext


def _ev(payload, *, sid="hl_allmids", ts=1000, context=RunContext.LIVE):
    return make_raw_event(source_id=sid, kind="/info:allMids", payload=payload,
                          fetched_at_ms=ts, context=context)


def test_put_get_roundtrip():
    s = SqliteRawStore()
    ev = _ev({"BTC": "60000"})
    assert s.put(ev) is True
    got = s.get(ev.raw_hash)
    assert got is not None and got.source_id == "hl_allmids" and got.payload == {"BTC": "60000"}


def test_dedupe_same_context_hash():
    s = SqliteRawStore()
    assert s.put(_ev({"BTC": "1"}, ts=1000)) is True
    assert s.put(_ev({"BTC": "1"}, ts=1001)) is False  # duplicate (same context+hash)
    assert s.count(context=RunContext.LIVE) == 1


def test_backfill_replayed_twice_zero_duplicates():
    s = SqliteRawStore()
    batch = [{"px": i} for i in range(20)]
    first = sum(s.put(_ev(p, ts=1000 + i)) for i, p in enumerate(batch))
    second = sum(s.put(_ev(p, ts=2000 + i)) for i, p in enumerate(batch))
    assert first == 20 and second == 0
    assert s.count(context=RunContext.LIVE) == 20


def test_contexts_never_mixed():
    s = SqliteRawStore()
    payload = {"BTC": "60000"}
    assert s.put(_ev(payload, context=RunContext.LIVE)) is True
    assert s.put(_ev(payload, context=RunContext.BACKTEST)) is True
    assert s.count(context=RunContext.LIVE) == 1
    assert s.count(context=RunContext.BACKTEST) == 1
    assert s.count() == 2
    assert set(s.contexts()) == {RunContext.LIVE, RunContext.BACKTEST}


def test_persistence_across_reopen(tmp_path):
    db = str(tmp_path / "raw.db")
    s1 = SqliteRawStore(db)
    s1.put(_ev({"BTC": "1"}, ts=1000))
    s1.close()
    s2 = SqliteRawStore(db)  # reopen same file
    assert s2.count(context=RunContext.LIVE) == 1
    # replay after restart is still deduped
    assert s2.put(_ev({"BTC": "1"}, ts=2000)) is False
    s2.close()


def test_recent_filters_and_orders():
    s = SqliteRawStore()
    s.put(_ev({"a": 1}, sid="src_a", ts=1000))
    s.put(_ev({"b": 2}, sid="src_b", ts=1001))
    s.put(_ev({"a": 2}, sid="src_a", ts=1002))
    rec = s.recent(source_id="src_a", context=RunContext.LIVE, limit=10)
    assert [e.source_id for e in rec] == ["src_a", "src_a"]
    assert rec[0].fetched_at_ms == 1002  # newest first
