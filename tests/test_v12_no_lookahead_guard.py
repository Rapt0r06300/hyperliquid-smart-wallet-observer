import pytest

from hl_observer.backtest.no_lookahead_guard import (
    assert_no_lookahead,
    find_lookahead_violations,
)


def test_clean_backtest_has_no_violations():
    events = [{"decision_ts_ms": 1000, "data_ts_ms": 900},
              {"decision_ts_ms": 2000, "data_ts_ms": 2000}]  # equal is allowed at gap 0
    assert find_lookahead_violations(events) == []
    assert_no_lookahead(events)


def test_future_data_is_a_leak():
    events = [{"decision_ts_ms": 1000, "data_ts_ms": 1500}]
    v = find_lookahead_violations(events)
    assert len(v) == 1 and v[0].index == 0
    with pytest.raises(AssertionError):
        assert_no_lookahead(events)


def test_min_gap_enforces_latency():
    events = [{"decision_ts_ms": 1000, "data_ts_ms": 1000}]
    assert find_lookahead_violations(events, min_gap_ms=0) == []
    assert len(find_lookahead_violations(events, min_gap_ms=100)) == 1  # data must be >=100ms old


def test_accepts_tuples_and_empty():
    assert find_lookahead_violations([]) == []
    assert find_lookahead_violations([(1000, 999)]) == []
    assert len(find_lookahead_violations([(1000, 1001)])) == 1
