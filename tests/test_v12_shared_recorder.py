from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.sources.shared_recorder import (
    get_shared_recorder,
    reset_shared_recorder,
    set_shared_recorder,
)


def test_singleton_identity():
    reset_shared_recorder()
    a = get_shared_recorder()
    b = get_shared_recorder()
    assert a is b and isinstance(a, CollectionRecorder)
    reset_shared_recorder()


def test_collection_populates_what_dashboard_reads():
    reset_shared_recorder()
    rec = get_shared_recorder()
    # simulate the collection path recording a fetch
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1000)
    # the dashboard would read the SAME instance
    assert get_shared_recorder().summary(now_ms=1100)["sources"] == 1
    reset_shared_recorder()


def test_set_and_reset():
    custom = CollectionRecorder()
    set_shared_recorder(custom)
    assert get_shared_recorder() is custom
    reset_shared_recorder()
    assert get_shared_recorder() is not custom
    reset_shared_recorder()
