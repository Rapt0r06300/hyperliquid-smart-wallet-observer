import pytest

from hyper_smart_observer.hyperliquid_client.normalization import (
    NormalizationError,
    normalize_position_snapshot,
    normalize_user_fill,
)

VALID = "0x" + "b" * 40


def test_normalize_user_fill_valid_fixture():
    fill = normalize_user_fill(
        {
            "coin": "ETH",
            "dir": "Open Long",
            "px": "2500.5",
            "sz": "0.25",
            "fee": "0.12",
            "time": 1700000000000,
            "hash": "0xabc",
            "closedPnl": "4.2",
        },
        VALID,
    )

    assert fill.wallet_address == VALID
    assert fill.coin == "ETH"
    assert fill.price == 2500.5
    assert fill.size == 0.25
    assert fill.raw_id == "0xabc"
    assert fill.closed_pnl == 4.2


def test_normalize_user_fill_refuses_missing_price():
    with pytest.raises(NormalizationError):
        normalize_user_fill(
            {"coin": "ETH", "dir": "Open Long", "sz": "0.25", "time": 1700000000000},
            VALID,
        )


def test_normalize_position_snapshot_valid_fixture():
    snapshot = normalize_position_snapshot(
        {
            "position": {
                "coin": "SOL",
                "szi": "4.5",
                "entryPx": "100",
                "unrealizedPnl": "12",
                "leverage": {"value": "3"},
            }
        },
        VALID,
    )

    assert snapshot.coin == "SOL"
    assert snapshot.size == 4.5
    assert snapshot.entry_price == 100.0
    assert snapshot.leverage == 3.0
