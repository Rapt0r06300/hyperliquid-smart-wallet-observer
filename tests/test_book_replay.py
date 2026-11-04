import pytest

from hl_observer.backtest.book_replay import BookReplayer, replay_book


def test_book_replay_accepts_exact_numeric_payloads():
    states = replay_book(
        [
            {"type": "snapshot", "ts_ms": "1000", "bids": [[99, "2"]], "asks": [[101, 3]]},
            {"type": "delta", "ts_ms": 1001, "side": "bid", "price": "100", "size": "1"},
        ]
    )

    assert states[-1].best_bid == 100.0
    assert states[-1].best_ask == 101.0
    assert states[-1].ts_ms == 1001


@pytest.mark.parametrize("timestamp", ["1000.5", 1000.5, True, float("nan")])
def test_book_replay_rejects_non_exact_timestamps_without_truncation(timestamp):
    with pytest.raises(ValueError, match="timestamps"):
        BookReplayer().apply_snapshot(bids=[], asks=[], ts_ms=timestamp)


def test_book_replay_rejects_unknown_event_type_instead_of_treating_it_as_delta():
    with pytest.raises(ValueError, match="event type"):
        replay_book([{"type": "unknown", "ts_ms": 1000, "side": "bid", "price": 100, "size": 1}])


def test_book_replay_rejects_non_finite_level_values():
    with pytest.raises(ValueError, match="prices and sizes"):
        BookReplayer().apply_snapshot(bids=[[100, "NaN"]], asks=[], ts_ms=1000)


def test_book_replay_rejects_negative_snapshot_size():
    with pytest.raises(ValueError, match="prices and sizes"):
        BookReplayer().apply_snapshot(bids=[[100, -1]], asks=[], ts_ms=1000)
