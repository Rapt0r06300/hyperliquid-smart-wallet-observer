from __future__ import annotations

import threading
from types import SimpleNamespace

import hl_observer.ui.status_routes as status_routes


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        hyperliquid=SimpleNamespace(info_base_url="https://example.invalid/info")
    )


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Client:
    payload = {"BTC": "101.25", "ETH": "bad", "SOL": "0"}
    calls: list[tuple[str, dict[str, str]]] = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, *, json: dict[str, str]) -> _Response:
        self.calls.append((url, json))
        return _Response(self.payload)


def test_live_all_mids_is_disabled_without_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", raising=False)

    result = status_routes._live_all_mids_marks(
        _settings(),
        raw_positions=[{"coin": "BTC"}],
        current_ms=10_000,
        cache={"fetched_at_ms": 0, "prices": {}, "error": None},
        lock=threading.Lock(),
    )

    assert result["read_status"] == "LIVE_MARKS_DISABLED"


def test_live_all_mids_uses_fresh_cache_without_network(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")

    class _NoNetworkClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("fresh cache must avoid network")

    monkeypatch.setattr(status_routes.httpx, "Client", _NoNetworkClient)
    result = status_routes._live_all_mids_marks(
        _settings(),
        raw_positions=[{"coin": "BTC"}],
        current_ms=2_000,
        cache={"fetched_at_ms": 1_500, "prices": {"BTC": 99.5}, "error": None},
        lock=threading.Lock(),
    )

    assert result["read_status"] == "OK_CACHE_LIVE_ALLMIDS"
    assert result["prices"] == {"BTC": 99.5}


def test_live_all_mids_reads_only_info_and_filters_invalid_prices(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    _Client.calls = []
    _Client.payload = {"BTC": "101.25", "ETH": "bad", "SOL": "0"}
    monkeypatch.setattr(status_routes.httpx, "Client", _Client)
    cache = {"fetched_at_ms": 0, "prices": {}, "error": "old"}

    result = status_routes._live_all_mids_marks(
        _settings(),
        raw_positions=[{"coin": "BTC"}, {"coin": "ETH"}, {"coin": "SOL"}],
        current_ms=20_000,
        cache=cache,
        lock=threading.Lock(),
    )

    assert _Client.calls == [("https://example.invalid/info", {"type": "allMids"})]
    assert result["read_status"] == "OK_LIVE_ALLMIDS"
    assert result["prices"] == {"BTC": 101.25}
    assert cache == {"fetched_at_ms": 20_000, "prices": {"BTC": 101.25}, "error": None}
    assert result["read_only"] is True


def test_live_all_mids_falls_back_to_recent_cache_on_bad_payload(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    _Client.payload = []
    monkeypatch.setattr(status_routes.httpx, "Client", _Client)
    cache = {"fetched_at_ms": 8_000, "prices": {"BTC": 98.0}, "error": None}

    result = status_routes._live_all_mids_marks(
        _settings(),
        raw_positions=[{"coin": "BTC"}],
        current_ms=10_000,
        cache=cache,
        lock=threading.Lock(),
    )

    assert result["read_status"] == "OK_STALE_CACHE_LIVE_ALLMIDS"
    assert result["prices"] == {"BTC": 98.0}
    assert "ValueError" in result["error"]
    assert "ValueError" in cache["error"]


def test_live_all_mids_fails_closed_when_bad_payload_has_no_usable_cache(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_STATUS_LIVE_MARKS_ENABLED", "1")
    _Client.payload = []
    monkeypatch.setattr(status_routes.httpx, "Client", _Client)
    cache = {"fetched_at_ms": 0, "prices": {}, "error": None}

    result = status_routes._live_all_mids_marks(
        _settings(),
        raw_positions=[{"coin": "BTC"}],
        current_ms=10_000,
        cache=cache,
        lock=threading.Lock(),
    )

    assert result["read_status"] == "LIVE_ALLMIDS_READ_FAILED"
    assert result["prices"] == {}
    assert "ValueError" in result["error"]
