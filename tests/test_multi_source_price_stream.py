from hl_observer.realtime.multi_source_price_stream import PriceEvent, merge_price_events


def test_multi_source_price_stream_orders_by_event_time():
    rows = merge_price_events([PriceEvent("b", "HYPE", 100, 101, 20), PriceEvent("a", "HYPE", 99, 100, 10)])
    assert [row.source for row in rows] == ["a", "b"]
    assert rows[0].mid == 99.5
