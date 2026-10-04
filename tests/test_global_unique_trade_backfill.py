from __future__ import annotations

import gzip
import json

from tools import backfill_global_unique_trade_counts as global_counts


def test_scan_candidate_extracts_exact_identities_without_global_state(tmp_path, monkeypatch):
    asset = tmp_path / "asset.jsonl.gz"
    raw = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"i": "a", "T": 1, "p": "10", "v": "1", "S": "Buy", "s": "BTCUSDT"},
            {"i": "b", "T": 2, "p": "11", "v": "2", "S": "Sell", "s": "BTCUSDT"},
            {"i": "a", "T": 1, "p": "10", "v": "1", "S": "Buy", "s": "BTCUSDT"},
        ],
    }
    with gzip.open(asset, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": json.dumps(raw)}) + "\n")
    monkeypatch.setattr(global_counts, "_download", lambda row, destination: asset)
    row = {
        "dataset_id": "sample",
        "venue": "bybit",
        "family": "trades",
        "symbol": "BTCUSDT",
    }

    result = global_counts._scan_candidate(row, tmp_path)

    assert result["dataset_id"] == "sample"
    assert result["trade_count_scanned"] == 3
    assert result["unique_trade_count"] == 2
    assert result["exact"] is True
    identities = result["identity_path"]
    with open(identities, encoding="utf-8") as handle:
        rows = [line.strip() for line in handle if line.strip()]
    assert rows == sorted(set(rows))
    assert len(rows) == 2


def test_unique_candidate_excludes_non_trade_zero_count_assets():
    base = {
        "dataset_id": "x",
        "trade_count_exact": True,
        "release_repository": "owner/repo",
        "release_tag": "tag",
        "release_asset": "asset.jsonl.gz",
        "sha256": "a" * 64,
        "bytes": 1,
    }
    assert global_counts._unique_candidate({**base, "family": "bbo", "trade_count": 0}) is False
    assert global_counts._unique_candidate({**base, "family": "l2Book", "trade_count": 100}) is False
    assert global_counts._unique_candidate({**base, "family": "trades", "trade_count": 0}) is False
    assert global_counts._unique_candidate({**base, "family": "trades", "trade_count": 1}) is True


def test_native_trade_keys_support_normalized_hyperliquid_fill_without_raw_envelope():
    record = {
        "raw_payload": {
            "time": 123,
            "px": "100.5",
            "sz": "2",
            "side": "B",
            "coin": "BTC",
            "hash": "0xabc",
            "oid": 7,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="BTC"
    )
    assert keys is not None
    assert len(keys) == 1
    assert keys[0].startswith("hyperliquid|copy_vault_fills|BTC|fallback|123|100.5|2|B|BTC|")


def test_native_trade_keys_support_normalized_binance_official_aggtrade_as_trades():
    record = {
        "raw_payload": {
            "agg_trade_id": "123456",
            "price": "101.25",
            "quantity": "0.75",
            "first_trade_id": "100",
            "last_trade_id": "102",
            "transact_time": 1790000000123,
            "is_buyer_maker": False,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="binance", family="trades", symbol="BTCUSDT"
    )
    assert keys == ["binance|trades|BTCUSDT|a|123456"]


def test_native_trade_keys_support_binance_archive_list_payload():
    record = {
        "raw_payload": [
            {"id": 11, "time": 1000, "price": "10", "qty": "1", "side": "BUY"},
            {"id": 12, "time": 1001, "price": "11", "qty": "2", "side": "SELL"},
        ]
    }
    keys = global_counts._native_trade_keys(
        record, venue="binance", family="trades", symbol="BTCUSDT"
    )
    assert keys == [
        "binance|trades|BTCUSDT|t|11",
        "binance|trades|BTCUSDT|t|12",
    ]


def test_native_trade_keys_support_normalized_copy_vault_fill_ts_ms():
    record = {
        "raw_payload": {
            "vault": "0xabc",
            "ts_ms": 1790000000123,
            "coin": "BTC",
            "px": 101.25,
            "sz": 0.75,
            "signe": 1,
            "dir": "Open Long",
            "hash": "0xfeed",
            "oid": 42,
            "start_position": 0.0,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="BTC"
    )
    assert keys is not None
    assert len(keys) == 1
    assert keys[0].startswith(
        "hyperliquid|copy_vault_fills|BTC|fallback|1790000000123|101.25|0.75|Open Long|BTC|"
    )


def test_native_trade_keys_support_gate_native_trade_id() -> None:
    record = {
        "raw_payload": {
            "channel": "futures.trades",
            "result": [
                {
                    "id": 987654321,
                    "create_time_ms": 1790991018232,
                    "contract": "ETH_USDT",
                    "price": "3500.1",
                    "size": 3,
                    "side": "sell",
                }
            ],
        }
    }
    keys = global_counts._native_trade_keys(
        record,
        venue="gate",
        family="trades",
        symbol="ETH_USDT",
    )
    assert keys == ["gate|trades|ETH_USDT|id|987654321"]


def test_native_trade_keys_fail_closed_when_composite_is_ambiguous():
    keys = global_counts._native_trade_keys(
        {"raw_payload": {"time": 1, "px": "10"}},
        venue="hyperliquid",
        family="fills",
        symbol="BTC",
    )
    assert keys is None

def test_native_trade_keys_support_hyperliquid_userfills_nested_envelope():
    record = {
        "raw_payload": {
            "channel": "userFills",
            "data": {
                "user": "0xabc",
                "isSnapshot": False,
                "fills": [
                    {"tid": 101, "time": 10, "px": "100", "sz": "1", "side": "B", "coin": "BTC"},
                    {"tid": 102, "time": 11, "px": "101", "sz": "2", "side": "A", "coin": "BTC"},
                ],
            },
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="0xabc"
    )
    assert keys == [
        "hyperliquid|copy_vault_fills|0xabc|tid|101",
        "hyperliquid|copy_vault_fills|0xabc|tid|102",
    ]



def test_bybit_archive_trd_match_id_is_canonical_native_identity():
    row = {
        "raw_payload": {
            "timestamp": "1790000000.125",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.1",
            "price": "100.5",
            "trdMatchID": "archive-match-123",
        }
    }
    keys = global_counts._native_trade_keys(
        row,
        venue="bybit",
        family="trades",
        symbol="BTCUSDT",
    )
    assert keys == ["bybit|trades|BTCUSDT|i|archive-match-123"]
