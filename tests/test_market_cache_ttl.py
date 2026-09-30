from hl_observer.market_signals.market_cache import MarketCache


def test_market_cache_ttl_expires():
    cache = MarketCache(ttl_ms=100)
    cache.set("HYPE", {"mid": 10}, now_ms=1000)
    assert cache.get("HYPE", now_ms=1050) == {"mid": 10}
    assert cache.get("HYPE", now_ms=1201) is None
