import inspect

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient


def test_rest_info_client_has_meta_and_user_read_only_methods():
    assert hasattr(HyperliquidInfoClient, "meta")
    assert hasattr(HyperliquidInfoClient, "clearinghouse_state")
    assert hasattr(HyperliquidInfoClient, "portfolio")
    assert hasattr(HyperliquidInfoClient, "historical_orders")
    assert hasattr(HyperliquidInfoClient, "user_funding")
    assert hasattr(HyperliquidInfoClient, "user_rate_limit")


def test_rest_info_client_v6_never_calls_exchange():
    source = inspect.getsource(HyperliquidInfoClient)

    assert "/exchange" not in source
    assert "place_order" not in source
