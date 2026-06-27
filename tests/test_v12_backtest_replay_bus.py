from hl_observer.backtest.book_replay import BookReplayer, replay_book
from hl_observer.backtest.trade_tick_replay import is_monotonic, replay_trade_ticks
from hl_observer.backtest.data_bus import DataBus
from hl_observer.backtest.materialized_cache import MaterializedCache


def test_book_reconstructs_l2_from_deltas():
    events = [
        {"type": "snapshot", "ts_ms": 1, "bids": [(100.0, 2.0), (99.0, 5.0)], "asks": [(101.0, 3.0)]},
        {"type": "delta", "ts_ms": 2, "side": "ask", "price": 100.5, "size": 1.0},   # better ask
        {"type": "delta", "ts_ms": 3, "side": "bid", "price": 100.0, "size": 0.0},    # remove best bid
    ]
    states = replay_book(events)
    assert states[0].best_bid == 100.0 and states[0].best_ask == 101.0
    assert states[1].best_ask == 100.5
    assert states[2].best_bid == 99.0 and states[2].spread_bps is not None


def test_trade_ticks_ordered_and_deduped():
    ticks = [{"id": "a", "ts_ms": 3}, {"id": "b", "ts_ms": 1}, {"id": "a", "ts_ms": 3}]
    out = replay_trade_ticks(ticks)
    assert [t["id"] for t in out] == ["b", "a"]      # ordered by ts, dup 'a' removed
    assert is_monotonic(out)


def test_data_bus_tier_fallthrough_and_cache():
    calls = {"local": 0, "api": 0}
    def local(k):
        calls["local"] += 1
        return None
    def api(k):
        calls["api"] += 1
        return {"k": k}
    bus = DataBus(local=local, api=api)
    assert bus.get("x") == {"k": "x"}     # miss local -> hit api
    assert bus.get("x") == {"k": "x"}     # cached now
    assert bus.hits["api"] == 1 and bus.hits["cache"] == 1 and calls["api"] == 1


def test_materialized_cache_computes_once():
    c = MaterializedCache()
    n = {"calls": 0}
    def compute():
        n["calls"] += 1
        return 42
    assert c.get_or_compute("k", compute) == 42
    assert c.get_or_compute("k", compute) == 42
    assert n["calls"] == 1 and c.hits == 1 and c.misses == 1
