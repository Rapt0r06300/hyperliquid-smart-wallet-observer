from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe


def test_ws_event_dedupe_blocks_repeat_key():
    dedupe = EventDedupe()

    assert dedupe.seen("abc") is False
    assert dedupe.seen("abc") is True


def test_hyperliquid_ws_subscription_ack_snapshot_dedupe():
    dedupe = EventDedupe()
    update = {
        "channel": "userFills",
        "data": {"user": "0x" + "a" * 40, "fills": [{"coin": "BTC", "hash": "fill-1"}]},
    }
    snapshot = {
        "channel": "userFills",
        "isSnapshot": True,
        "data": {"user": "0x" + "a" * 40, "fills": [{"coin": "BTC", "hash": "fill-1"}]},
    }
    mixed_snapshot = {
        "channel": "userFills",
        "isSnapshot": True,
        "data": {
            "user": "0x" + "a" * 40,
            "fills": [
                {"coin": "BTC", "hash": "fill-1"},
                {"coin": "ETH", "hash": "fill-2"},
            ],
        },
    }

    assert dedupe.accept_hyperliquid_message(update) is True
    assert dedupe.accept_hyperliquid_message(snapshot) is False
    assert dedupe.accept_hyperliquid_message(mixed_snapshot) is True
    assert dedupe.accept_hyperliquid_message(mixed_snapshot) is False
