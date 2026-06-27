import pytest

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult
from hyper_smart_observer.storage.database import initialize_database
from hyper_smart_observer.wallet_discovery.collector import HyperliquidReadOnlyCollector

VALID_1 = "0x" + "c" * 40
VALID_2 = "0x" + "d" * 40


class FakeCollectorClient:
    def __init__(self, fail_wallet=None):
        self.fail_wallet = fail_wallet

    def collect_user_fills_by_time_paginated(self, address, start_time_ms, end_time_ms, max_pages=None):
        if address == self.fail_wallet:
            raise RuntimeError("wallet failed")
        return PaginationResult(
            fills=[
                {
                    "coin": "BTC",
                    "side": "buy",
                    "px": "100",
                    "sz": "1",
                    "fee": "0.01",
                    "time": start_time_ms + 1,
                    "hash": address[-8:],
                }
            ],
            pages_fetched=1,
            stopped_reason="empty_response",
        )

    def get_clearinghouse_state(self, address):
        return {
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "1", "entryPx": "100", "unrealizedPnl": "0"}}
            ]
        }


def test_collector_refuses_without_network_read(tmp_path):
    config = AppConfig(database_path=tmp_path / "collector.sqlite3", enable_network_reads=False)
    collector = HyperliquidReadOnlyCollector(config, client=FakeCollectorClient())

    with pytest.raises(SafetyViolation):
        collector.collect_wallets([VALID_1], start_time_ms=1, end_time_ms=2)


def test_collector_refuses_invalid_address(tmp_path):
    config = AppConfig(database_path=tmp_path / "collector.sqlite3", enable_network_reads=True)
    collector = HyperliquidReadOnlyCollector(config, client=FakeCollectorClient())

    with pytest.raises(ValueError):
        collector.collect_wallets(["0x1234"], start_time_ms=1, end_time_ms=2, network_read=True)


def test_collector_continues_if_one_wallet_fails(tmp_path):
    config = AppConfig(database_path=tmp_path / "collector.sqlite3", enable_network_reads=True)
    initialize_database(config)
    collector = HyperliquidReadOnlyCollector(config, client=FakeCollectorClient(fail_wallet=VALID_1))

    report = collector.collect_wallets(
        [VALID_1, VALID_2],
        start_time_ms=1700000000000,
        end_time_ms=1700000001000,
        network_read=True,
    )

    assert report.wallets_requested == 2
    assert report.wallets_collected == 1
    assert report.fills_inserted == 1
    assert report.position_snapshots_inserted == 1
    assert VALID_1 in report.errors
