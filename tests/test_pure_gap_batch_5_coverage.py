from __future__ import annotations

from hl_observer.connectors.hyperliquid_readonly import HyperliquidReadonlyConnector


def test_hyperliquid_readonly_short_side_alias_and_dir_fallback() -> None:
    connector = HyperliquidReadonlyConnector()
    base = {"coin": "ETH", "px": "100", "sz": "2", "time": 123}

    assert connector.normalize_fill({**base, "side": "a"})["side"] == "SHORT"
    assert connector.normalize_fill({**base, "dir": "close short"})["side"] == "SHORT"
