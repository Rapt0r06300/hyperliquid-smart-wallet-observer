from hl_observer.ui.charts.series import (
    build_candle_series, build_drawdown_series, build_edge_series, build_equity_series,
    build_liquidity_series, build_no_trade_markers, build_position_markers,
    build_source_latency_series, incremental_update,
)


def test_empty_in_empty_out_no_fake_points():
    assert build_equity_series([]) == []
    assert build_drawdown_series([]) == []
    assert build_candle_series([]) == []
    assert build_position_markers([]) == []
    assert build_no_trade_markers([]) == []


def test_equity_sorted_deduped():
    s = build_equity_series([{"time": 3, "equity": 30}, {"time": 1, "equity": 10}, {"time": 1, "equity": 11}])
    assert [p["time"] for p in s] == [1, 3]
    assert s[0]["value"] == 11.0   # last write wins on dup time


def test_drawdown_is_nonpositive_and_tracks_peak():
    eq = [{"time": 1, "equity": 100}, {"time": 2, "equity": 120}, {"time": 3, "equity": 90}]
    dd = build_drawdown_series(eq)
    assert dd[0]["value"] == 0.0 and dd[1]["value"] == 0.0
    assert dd[2]["value"] == -25.0   # (90-120)/120


def test_candle_and_line_series():
    c = build_candle_series([{"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5}])
    assert c[0]["high"] == 2.0
    assert build_edge_series([{"time": 1, "edge_bps": 12.5}])[0]["value"] == 12.5
    assert build_liquidity_series([{"time": 1, "liquidity_score": 0.4}])[0]["value"] == 0.4
    assert build_source_latency_series([{"time": 1, "latency_ms": 80}])[0]["value"] == 80.0


def test_markers_shapes():
    m = build_position_markers([{"time": 5, "side": "LONG", "action": "OPEN", "coin": "BTC"}])
    assert m[0]["shape"] == "arrowUp" and m[0]["position"] == "belowBar"
    nt = build_no_trade_markers([{"time": 7, "code": "STALE_SIGNAL"}])
    assert nt[0]["text"] == "STALE_SIGNAL"


def test_incremental_update_dedupes_time():
    s = build_equity_series([{"time": 1, "equity": 10}])
    s = incremental_update(s, {"time": 1, "value": 11})
    s = incremental_update(s, {"time": 2, "value": 20})
    assert [(p["time"], p["value"]) for p in s] == [(1, 11), (2, 20)]
