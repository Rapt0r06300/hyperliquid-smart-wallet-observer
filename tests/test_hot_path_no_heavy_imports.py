from hl_observer.runtime.hot_path import hot_path_event_from_fill, hot_path_has_heavy_dependencies


def test_hot_path_stays_light_and_builds_event():
    event = hot_path_event_from_fill({"coin": "HYPE", "dir": "Open Long", "wallet": "0xabc"}, observed_at_ms=10)
    assert event.coin == "HYPE"
    assert event.event_id.startswith("hot:")
    assert hot_path_has_heavy_dependencies() is False
