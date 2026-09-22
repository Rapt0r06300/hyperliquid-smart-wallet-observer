from __future__ import annotations

import gzip
import hashlib
import io
import zipfile
from datetime import date

import pytest

from hl_observer.data_sources.official_archive_backfill import (
    binance_usdm_aggtrades_url,
    bybit_trades_url,
    fetch_official_archive_day,
    iter_days,
)


def _zip_csv(text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-aggTrades-2026-09-20.csv", text)
    return out.getvalue()


def test_archive_urls_are_exact_and_public() -> None:
    day = date(2026, 9, 20)
    assert binance_usdm_aggtrades_url("btcusdt", day) == (
        "https://data.binance.vision/data/futures/um/daily/aggTrades/"
        "BTCUSDT/BTCUSDT-aggTrades-2026-09-20.zip"
    )
    assert bybit_trades_url("ethusdt", day) == (
        "https://public.bybit.com/trading/ETHUSDT/ETHUSDT2026-09-20.csv.gz"
    )


def test_archive_range_is_bounded() -> None:
    assert len(iter_days(date(2026, 9, 18), date(2026, 9, 20), max_days=3)) == 3
    with pytest.raises(ValueError):
        iter_days(date(2026, 9, 18), date(2026, 9, 21), max_days=3)


def test_binance_archive_requires_checksum_and_keeps_historical_clock_honest() -> None:
    payload = _zip_csv(
        "1,100.5,0.25,10,12,1790000000000,true\n"
        "2,100.6,0.50,13,15,1790000000100,false\n"
    )
    checksum = hashlib.sha256(payload).hexdigest().encode() + b"  archive.zip\n"
    result = fetch_official_archive_day(
        venue="binance",
        coin="BTC",
        symbol="BTCUSDT",
        day=date(2026, 9, 20),
        fetch_bytes=lambda url: checksum if url.endswith(".CHECKSUM") else payload,
    )
    assert len(result.events) == 2
    first = result.events[0]
    assert result.checksum_verified is True
    assert first.source_id == "binance_usdm_official_archive"
    assert first.channel == "trades"
    assert first.exchange_ts_ms == 1790000000000
    assert first.received_ts_ms == first.exchange_ts_ms
    assert first.local_monotonic_ns is None
    assert first.sequence == 1
    assert first.provenance["timestamp_semantics"] == "historical_exchange_time_only"
    assert first.provenance["historical_receive_timestamp_available"] is False


def test_binance_checksum_mismatch_fails_closed() -> None:
    payload = _zip_csv("1,100.5,0.25,10,12,1790000000000,true\n")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        fetch_official_archive_day(
            venue="binance",
            coin="BTC",
            symbol="BTCUSDT",
            day=date(2026, 9, 20),
            fetch_bytes=lambda url: (b"0" * 64 + b"  archive.zip\n") if url.endswith(".CHECKSUM") else payload,
        )


def test_bybit_archive_parses_fractional_seconds_without_fake_sequence() -> None:
    csv_text = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID\n"
        "1790000000.125,BTCUSDT,Buy,0.1,100.5,PlusTick,abc\n"
    )
    result = fetch_official_archive_day(
        venue="bybit",
        coin="BTC",
        symbol="BTCUSDT",
        day=date(2026, 9, 20),
        fetch_bytes=lambda _url: gzip.compress(csv_text.encode()),
    )
    event = result.events[0]
    assert event.source_id == "bybit_official_archive"
    assert event.exchange_ts_ms == 1790000000125
    assert event.sequence is None
    assert event.local_monotonic_ns is None
    assert event.provenance["archive_checksum_verified"] is False


def test_archive_event_limit_is_enforced() -> None:
    payload = _zip_csv(
        "1,100.5,0.25,10,12,1790000000000,true\n"
        "2,100.6,0.50,13,15,1790000000100,false\n"
        "3,100.7,0.75,16,18,1790000000200,false\n"
    )
    checksum = hashlib.sha256(payload).hexdigest().encode() + b"  archive.zip\n"
    result = fetch_official_archive_day(
        venue="binance",
        coin="BTC",
        symbol="BTCUSDT",
        day=date(2026, 9, 20),
        fetch_bytes=lambda url: checksum if url.endswith(".CHECKSUM") else payload,
        max_events=2,
    )
    assert len(result.events) == 2
