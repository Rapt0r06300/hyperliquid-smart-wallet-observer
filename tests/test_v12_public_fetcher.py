from hl_observer.collection.public_fetcher import (
    MemoryFetchCache,
    PublicFetchRequest,
    fetch_public_page,
)
from hl_observer.sources.registry import SourceRegistry
from hl_observer.storage.raw_store import RawStore


def test_public_fetcher_records_provenance_raw_and_cache():
    calls = {"n": 0}

    def transport(url: str):
        calls["n"] += 1
        return 200, {}, "<html>0x1111111111111111111111111111111111111111</html>"

    registry = SourceRegistry()
    raw_store = RawStore()
    cache = MemoryFetchCache()
    request = PublicFetchRequest(url="https://app.hyperliquid.xyz/explorer", source_id="hl_explorer")

    first = fetch_public_page(request, now_ms=1_000, transport=transport, cache=cache, registry=registry, raw_store=raw_store)
    second = fetch_public_page(request, now_ms=1_500, transport=transport, cache=cache, registry=registry, raw_store=raw_store)

    assert first.ok is True
    assert first.from_cache is False
    assert second.ok is True
    assert second.from_cache is True
    assert calls["n"] == 1
    assert registry.health("hl_explorer", now_ms=2_000).usable is True
    assert raw_store.count() == 1


def test_public_fetcher_refuses_non_public_url_without_transport_call():
    def transport(url: str):
        raise AssertionError("transport should not be called")

    result = fetch_public_page(
        PublicFetchRequest(url="file:///secret.txt", source_id="bad"),
        now_ms=1,
        transport=transport,
    )

    assert result.ok is False
    assert result.external_action is False
    assert "INVALID_PUBLIC_URL" in result.warnings


def test_public_fetcher_blocks_login_or_captcha_page_as_bad_source():
    registry = SourceRegistry()

    def transport(url: str):
        return 200, {}, "<html>Please sign in to continue. captcha</html>"

    result = fetch_public_page(
        PublicFetchRequest(url="https://example.com/private", source_id="login"),
        now_ms=1,
        transport=transport,
        registry=registry,
    )

    assert result.ok is False
    assert result.body is None
    assert "LOGIN_OR_CAPTCHA_PAGE" in result.warnings
    assert registry.health("login", now_ms=2).usable is False
