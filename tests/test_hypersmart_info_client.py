import pytest

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient
from hyper_smart_observer.hyperliquid_client.rate_limiter import LocalRateLimiter


VALID = "0x" + "a" * 40


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(self.responses.pop(0))


def _client(responses, config=None):
    cfg = config or AppConfig(enable_network_reads=True, info_min_request_interval_ms=0)
    fake = FakeHttpClient(responses)
    client = HyperliquidInfoClient(
        cfg,
        http_client=fake,
        rate_limiter=LocalRateLimiter(0),
    )
    return client, fake


def test_post_info_refuses_url_containing_forbidden_execution_path():
    cfg = AppConfig(
        enable_network_reads=True,
        hyperliquid_info_base_url="https://api.hyperliquid-testnet.xyz/" + "exchange",
    )
    client, _ = _client([{}], cfg)

    with pytest.raises(SafetyViolation):
        client.post_info({"type": "meta"})


def test_post_info_uses_only_info_endpoint():
    client, fake = _client([{"universe": []}])

    assert client.get_meta() == {"universe": []}
    assert fake.calls[0]["url"].endswith("/info")
    assert fake.calls[0]["json"] == {"type": "meta"}


def test_get_user_fills_builds_expected_payload():
    client, fake = _client([[{"coin": "BTC"}]])

    client.get_user_fills(VALID)

    assert fake.calls[0]["json"] == {"type": "userFills", "user": VALID}


def test_get_user_fills_by_time_builds_expected_payload():
    client, fake = _client([[{"time": 1700000000000}]])

    client.get_user_fills_by_time(VALID, 1700000000000, 1700000001000)

    assert fake.calls[0]["json"] == {
        "type": "userFillsByTime",
        "user": VALID,
        "startTime": 1700000000000,
        "endTime": 1700000001000,
    }


def test_pagination_stops_on_empty_response():
    client, _ = _client([[]])

    result = client.collect_user_fills_by_time_paginated(VALID, 1000, 2000, max_pages=5)

    assert result.pages_fetched == 1
    assert result.fills == []
    assert result.stopped_reason == "empty_response"


def test_pagination_stops_on_max_pages():
    client, _ = _client([
        [{"time": 1001}],
        [{"time": 1003}],
    ])

    result = client.collect_user_fills_by_time_paginated(VALID, 1000, 3000, max_pages=2)

    assert result.pages_fetched == 2
    assert result.stopped_reason == "max_pages_reached"


def test_pagination_stops_if_timestamp_does_not_progress():
    client, _ = _client([[{"time": 1000}]])

    result = client.collect_user_fills_by_time_paginated(VALID, 1000, 3000, max_pages=5)

    assert result.pages_fetched == 1
    assert result.stopped_reason == "timestamp_not_progressing"
