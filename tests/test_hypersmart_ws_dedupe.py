from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe


def test_ws_event_dedupe_blocks_repeat_key():
    dedupe = EventDedupe()

    assert dedupe.seen("abc") is False
    assert dedupe.seen("abc") is True
