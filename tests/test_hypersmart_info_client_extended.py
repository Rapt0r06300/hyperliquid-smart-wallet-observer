from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient
from hyper_smart_observer.hyperliquid_client.rate_limiter import LocalRateLimiter


VALID = "0x" + "b" * 40


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append(json)
        return FakeResponse({} if json["type"] not in {"historicalOrders"} else [])


def _client():
    fake = FakeHttp()
    client = HyperliquidInfoClient(
        AppConfig(enable_network_reads=True, info_min_request_interval_ms=0),
        http_client=fake,
        rate_limiter=LocalRateLimiter(0),
    )
    return client, fake


def test_extended_info_payloads_are_readonly_info_types():
    client, fake = _client()

    client.get_order_status(VALID, 123)
    client.get_portfolio(VALID)
    client.get_user_fees(VALID)
    client.get_user_rate_limit(VALID)

    assert [call["type"] for call in fake.calls] == [
        "orderStatus",
        "portfolio",
        "userFees",
        "userRateLimit",
    ]
    assert all(call["user"] == VALID for call in fake.calls)
