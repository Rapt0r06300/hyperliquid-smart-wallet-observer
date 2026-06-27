from hl_observer.storage.raw_store import (
    RawEvent,
    RawStore,
    compute_raw_hash,
    make_raw_event,
)
from hl_observer.storage.run_context import RunContext


def _ev(payload, *, sid="hl_allmids", kind="/info:allMids", ts=1000, context=RunContext.LIVE):
    return make_raw_event(
        source_id=sid, kind=kind, payload=payload, fetched_at_ms=ts, context=context
    )


def test_hash_is_stable_and_order_independent():
    a = compute_raw_hash({"b": 2, "a": 1})
    b = compute_raw_hash({"a": 1, "b": 2})
    assert a == b
    assert compute_raw_hash({"a": 1}) != compute_raw_hash({"a": 2})


def test_put_then_get():
    store = RawStore()
    ev = _ev({"BTC": "60000"})
    assert store.put(ev) is True
    got = store.get(ev.raw_hash)
    assert got is not None and got.source_id == "hl_allmids"


def test_dedupe_same_payload_same_context():
    store = RawStore()
    assert store.put(_ev({"BTC": "60000"}, ts=1000)) is True
    assert store.put(_ev({"BTC": "60000"}, ts=1001)) is False  # identical raw -> dup
    assert store.count(context=RunContext.LIVE) == 1


def test_backfill_replayed_twice_zero_duplicates():
    """V12 dedupe contract: replaying a backfill must add zero rows."""
    store = RawStore()
    batch = [{"px": i} for i in range(20)]
    first = sum(store.put(_ev(p, ts=1000 + i)) for i, p in enumerate(batch))
    second = sum(store.put(_ev(p, ts=2000 + i)) for i, p in enumerate(batch))
    assert first == 20
    assert second == 0
    assert store.count(context=RunContext.LIVE) == 20


def test_contexts_never_mixed():
    """Same payload in LIVE and BACKTEST are distinct rows; counts stay separated."""
    store = RawStore()
    payload = {"BTC": "60000"}
    assert store.put(_ev(payload, context=RunContext.LIVE)) is True
    assert store.put(_ev(payload, context=RunContext.BACKTEST)) is True
    assert store.put(_ev(payload, context=RunContext.REPLAY)) is True
    assert store.count(context=RunContext.LIVE) == 1
    assert store.count(context=RunContext.BACKTEST) == 1
    assert store.count(context=RunContext.REPLAY) == 1
    assert store.count() == 3
    # a LIVE lookup must not see the BACKTEST/REPLAY copies as "missing"
    assert store.get(compute_raw_hash(payload), context=RunContext.LIVE) is not None


def test_recent_filters_by_source_and_context():
    store = RawStore()
    store.put(_ev({"a": 1}, sid="src_a", ts=1000))
    store.put(_ev({"b": 2}, sid="src_b", ts=1001))
    store.put(_ev({"a": 2}, sid="src_a", ts=1002))
    rec = store.recent(source_id="src_a", context=RunContext.LIVE, limit=10)
    assert [e.source_id for e in rec] == ["src_a", "src_a"]
    assert rec[0].fetched_at_ms == 1002  # newest first


def test_event_id_includes_context():
    ev = _ev({"x": 1}, context=RunContext.TEST_FIXTURE)
    assert ev.event_id.startswith("TEST_FIXTURE:")


def test_eviction_bounded_per_context():
    store = RawStore(max_per_context=5)
    for i in range(10):
        store.put(_ev({"i": i}, ts=1000 + i))
    assert store.count(context=RunContext.LIVE) == 5
    # an evicted (oldest) payload can be re-inserted (its hash left the seen set)
    assert store.put(_ev({"i": 0}, ts=9000)) is True


def test_store_has_no_execution_surface():
    pub = {n for n in dir(RawStore) if not n.startswith("_")}
    for bad in ("submit", "place", "order", "sign", "send", "execute", "fetch"):
        assert not any(bad in n.lower() for n in pub)


def test_make_raw_event_accepts_string_context():
    ev = make_raw_event(
        source_id="s", kind="k", payload={"a": 1}, fetched_at_ms=1, context="backtest"
    )
    assert ev.context == RunContext.BACKTEST
