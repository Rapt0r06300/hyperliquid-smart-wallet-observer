import pytest

from hl_observer.config.loader import load_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient, HyperliquidInfoError
from hl_observer.security.mainnet_guard import (
    MainnetExecutionForbidden,
    assert_mainnet_execution_disabled,
)


def test_no_mainnet_execution_by_default(monkeypatch):
    monkeypatch.delenv("HL_ENABLE_MAINNET_EXECUTION", raising=False)
    settings = load_settings()

    assert not settings.execution.enable_mainnet_execution
    assert_mainnet_execution_disabled(settings)


def test_mainnet_execution_impossible_even_if_env_true(monkeypatch):
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "true")
    settings = load_settings()

    with pytest.raises(MainnetExecutionForbidden):
        assert_mainnet_execution_disabled(settings)


def test_mainnet_exchange_endpoint_forbidden():
    with pytest.raises(HyperliquidInfoError):
        HyperliquidInfoClient("https://api.hyperliquid.xyz/" + "exchange")


def test_rest_info_client_has_no_exchange_method():
    assert not hasattr(HyperliquidInfoClient, "exchange")
    assert not hasattr(HyperliquidInfoClient, "place_order")
