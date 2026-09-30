"""Official public Binance/Bybit archive backfill for replay evidence.

Only documented public archive hosts are used. Historical archives do not contain
Alina receive-time or monotonic-clock evidence, so emitted records explicitly mark
exchange-time-only semantics and leave local_monotonic_ns missing. V2 gates therefore
cannot silently promote them to live-quality SAFE evidence.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from hl_observer.collection.tick_dataset import TickEnvelope

BINANCE_USDM_ARCHIVE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
BYBIT_TRADING_ARCHIVE = "https://public.bybit.com/trading"
DEFAULT_MAX_COMPRESSED_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_DECOMPRESSED_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_EVENTS = 2_000_000


@dataclass(frozen=True, slots=True)
class ArchiveDay:
    venue: str
    coin: str
    symbol: str
    day: date
    source_url: str
    compressed_sha256: str
    checksum_verified: bool
    events: tuple[TickEnvelope, ...]


@dataclass(frozen=True, slots=True)
class ArchiveStream:
    venue: str
    coin: str
    symbol: str
    day: date
    source_url: str
    compressed_sha256: str
    checksum_verified: bool
    events: Iterable[TickEnvelope]


def iter_days(start: date, end: date, *, max_days: int = 7) -> tuple[date, ...]:
    if end < start:
        raise ValueError("end must be on or after start")
    limit = max(1, int(max_days))
    count = (end - start).days + 1
    if count > limit:
        raise ValueError(f"archive window exceeds max_days={limit}")
    return tuple(start + timedelta(days=index) for index in range(count))


def binance_usdm_aggtrades_url(symbol: str, day: date) -> str:
    normalized = _symbol(symbol)
    stamp = day.isoformat()
    return f"{BINANCE_USDM_ARCHIVE}/{normalized}/{normalized}-aggTrades-{stamp}.zip"


def bybit_trades_url(symbol: str, day: date) -> str:
    normalized = _symbol(symbol)
    return f"{BYBIT_TRADING_ARCHIVE}/{normalized}/{normalized}{day.isoformat()}.csv.gz"


def fetch_official_archive_stream(
    *,
    venue: str,
    coin: str,
    symbol: str,
    day: date,
    fetch_bytes: Callable[[str], bytes] | None = None,
    max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> ArchiveStream:
    venue_key = str(venue or "").strip().lower()
    normalized_coin = str(coin or "").strip().upper()
    normalized_symbol = _symbol(symbol)
    if not normalized_coin:
        raise ValueError("coin is required")
    getter = fetch_bytes or _http_get_bytes

    if venue_key == "binance":
        url = binance_usdm_aggtrades_url(normalized_symbol, day)
        payload = _bounded_download(getter, url, max_compressed_bytes)
        checksum_payload = _bounded_download(getter, url + ".CHECKSUM", 64 * 1024)
        digest = hashlib.sha256(payload).hexdigest()
        expected = _checksum_from_payload(checksum_payload)
        if digest.lower() != expected.lower():
            raise ValueError("Binance archive SHA256 mismatch")
        events = _limit(
            _iter_binance_archive_payload(
                payload,
                coin=normalized_coin,
                symbol=normalized_symbol,
                source_url=url,
                archive_sha256=digest,
                checksum_verified=True,
                max_decompressed_bytes=max_decompressed_bytes,
            ),
            max_events,
        )
        verified = True
    elif venue_key == "bybit":
        url = bybit_trades_url(normalized_symbol, day)
        payload = _bounded_download(getter, url, max_compressed_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        events = _limit(
            _iter_bybit_archive_payload(
                payload,
                coin=normalized_coin,
                symbol=normalized_symbol,
                source_url=url,
                archive_sha256=digest,
            ),
            max_events,
        )
        verified = False
    else:
        raise ValueError("venue must be 'binance' or 'bybit'")

    return ArchiveStream(
        venue=venue_key,
        coin=normalized_coin,
        symbol=normalized_symbol,
        day=day,
        source_url=url,
        compressed_sha256=digest,
        checksum_verified=verified,
        events=events,
    )


def fetch_official_archive_day(
    *,
    venue: str,
    coin: str,
    symbol: str,
    day: date,
    fetch_bytes: Callable[[str], bytes] | None = None,
    max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> ArchiveDay:
    stream = fetch_official_archive_stream(
        venue=venue,
        coin=coin,
        symbol=symbol,
        day=day,
        fetch_bytes=fetch_bytes,
        max_compressed_bytes=max_compressed_bytes,
        max_decompressed_bytes=max_decompressed_bytes,
        max_events=max_events,
    )
    events = tuple(stream.events)
    if not events:
        raise ValueError("official archive contained no parseable trade events")
    return ArchiveDay(
        venue=stream.venue,
        coin=stream.coin,
        symbol=stream.symbol,
        day=stream.day,
        source_url=stream.source_url,
        compressed_sha256=stream.compressed_sha256,
        checksum_verified=stream.checksum_verified,
        events=events,
    )


def parse_binance_aggtrades_csv(
    text: str,
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
    checksum_verified: bool,
) -> Iterable[TickEnvelope]:
    return _parse_binance_reader(
        csv.reader(io.StringIO(text)),
        coin=coin,
        symbol=symbol,
        source_url=source_url,
        archive_sha256=archive_sha256,
        checksum_verified=checksum_verified,
    )


def _parse_binance_reader(
    reader: Iterable[list[str]],
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
    checksum_verified: bool,
) -> Iterable[TickEnvelope]:
    iterator = iter(reader)
    first = next(iterator, None)
    if first is None:
        return ()
    header = [str(value).strip().lower() for value in first]
    has_header = any(token in {
        "agg_trade_id", "aggtradeid", "price", "quantity", "qty",
        "transact_time", "timestamp",
    } for token in header)
    rows: Iterable[list[str]]
    if has_header:
        rows = iterator
        positions = {name: index for index, name in enumerate(header)}
    else:
        rows = _prepend(first, iterator)
        positions = {}

    def field(row: list[str], names: tuple[str, ...], fallback: int) -> str:
        for name in names:
            index = positions.get(name)
            if index is not None and index < len(row):
                return row[index]
        return row[fallback] if fallback < len(row) else ""

    def generate() -> Iterable[TickEnvelope]:
        for row in rows:
            try:
                event_id = field(row, ("agg_trade_id", "aggtradeid", "id"), 0)
                price = field(row, ("price",), 1)
                quantity = field(row, ("quantity", "qty"), 2)
                first_trade_id = field(row, ("first_trade_id", "firsttradeid"), 3)
                last_trade_id = field(row, ("last_trade_id", "lasttradeid"), 4)
                timestamp = _epoch_ms(field(row, ("transact_time", "timestamp", "time"), 5))
                maker = _boolish(field(row, ("is_buyer_maker", "isbuyermaker"), 6))
                sequence = int(event_id)
                float(price)
                float(quantity)
            except (TypeError, ValueError, OverflowError):
                continue
            yield _historical_trade_envelope(
                source_id="binance_usdm_official_archive",
                coin=coin,
                symbol=symbol,
                exchange_ts_ms=timestamp,
                sequence=sequence,
                raw={
                    "agg_trade_id": event_id,
                    "price": price,
                    "quantity": quantity,
                    "first_trade_id": first_trade_id,
                    "last_trade_id": last_trade_id,
                    "transact_time": timestamp,
                    "is_buyer_maker": maker,
                },
                source_url=source_url,
                archive_sha256=archive_sha256,
                checksum_verified=checksum_verified,
            )
    return generate()


def parse_bybit_trades_csv(
    text: str,
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
) -> Iterable[TickEnvelope]:
    return _parse_bybit_reader(
        csv.DictReader(io.StringIO(text)),
        coin=coin,
        symbol=symbol,
        source_url=source_url,
        archive_sha256=archive_sha256,
    )


def _parse_bybit_reader(
    reader: Iterable[dict[str, Any]],
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
) -> Iterable[TickEnvelope]:
    def generate() -> Iterable[TickEnvelope]:
        for row in reader:
            try:
                timestamp = _epoch_ms(row.get("timestamp") or row.get("time") or row.get("trade_time_ms"))
                price = str(row.get("price") or "")
                size = str(row.get("size") or row.get("qty") or "")
                float(price)
                float(size)
            except (TypeError, ValueError, OverflowError):
                continue
            yield _historical_trade_envelope(
                source_id="bybit_official_archive",
                coin=coin,
                symbol=symbol,
                exchange_ts_ms=timestamp,
                sequence=None,
                raw={str(key): value for key, value in row.items() if key is not None},
                source_url=source_url,
                archive_sha256=archive_sha256,
                checksum_verified=False,
            )
    return generate()


def _iter_binance_archive_payload(
    payload: bytes,
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
    checksum_verified: bool,
    max_decompressed_bytes: int,
) -> Iterable[TickEnvelope]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        if len(files) != 1:
            raise ValueError("expected exactly one file in Binance archive")
        info = files[0]
        if info.file_size > max(1, int(max_decompressed_bytes)):
            raise ValueError("archive exceeds decompressed size limit")
        with archive.open(info, "r") as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
                yield from _parse_binance_reader(
                    csv.reader(text),
                    coin=coin,
                    symbol=symbol,
                    source_url=source_url,
                    archive_sha256=archive_sha256,
                    checksum_verified=checksum_verified,
                )


def _iter_bybit_archive_payload(
    payload: bytes,
    *,
    coin: str,
    symbol: str,
    source_url: str,
    archive_sha256: str,
) -> Iterable[TickEnvelope]:
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from _parse_bybit_reader(
                csv.DictReader(text),
                coin=coin,
                symbol=symbol,
                source_url=source_url,
                archive_sha256=archive_sha256,
            )


def _historical_trade_envelope(
    *,
    source_id: str,
    coin: str,
    symbol: str,
    exchange_ts_ms: int,
    sequence: int | None,
    raw: dict[str, Any],
    source_url: str,
    archive_sha256: str,
    checksum_verified: bool,
) -> TickEnvelope:
    return TickEnvelope(
        source_id=source_id,
        channel="trades",
        instrument=symbol,
        event_kind="HISTORICAL",
        raw_payload=raw,
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=exchange_ts_ms,
        local_monotonic_ns=None,
        connection_id=None,
        sequence=sequence,
        provenance={
            "access": "public_read_only",
            "authenticated": False,
            "transport": "https",
            "timestamp_semantics": "historical_exchange_time_only",
            "historical_receive_timestamp_available": False,
            "archive_source_url": source_url,
            "archive_sha256": archive_sha256,
            "archive_checksum_verified": bool(checksum_verified),
            "canonical_coin": coin,
        },
        parsed_summary={
            "historical_archive": True,
            "historical_receive_timestamp_available": False,
            "archive_checksum_verified": bool(checksum_verified),
        },
    )


def _bounded_download(fetch_bytes: Callable[[str], bytes], url: str, maximum: int) -> bytes:
    payload = fetch_bytes(url)
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("archive fetcher must return bytes")
    value = bytes(payload)
    if len(value) > max(1, int(maximum)):
        raise ValueError("archive exceeds compressed size limit")
    return value


def _http_get_bytes(url: str) -> bytes:
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _checksum_from_payload(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="strict").strip()
    token = text.split()[0] if text else ""
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError("invalid checksum sidecar")
    return token.lower()


def _epoch_ms(value: Any) -> int:
    number = float(value)
    if number <= 0:
        raise ValueError("timestamp must be positive")
    if number < 10_000_000_000:
        number *= 1000.0
    return int(number)


def _boolish(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}


def _symbol(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized or not all(char.isalnum() or char in {"_", "-"} for char in normalized):
        raise ValueError("invalid archive symbol")
    return normalized


def _prepend(first: list[str], rows: Iterable[list[str]]) -> Iterable[list[str]]:
    yield first
    yield from rows


def _limit(rows: Iterable[TickEnvelope], maximum: int) -> Iterable[TickEnvelope]:
    limit = max(1, int(maximum))
    for index, row in enumerate(rows):
        if index >= limit:
            break
        yield row


__all__ = [
    "ArchiveDay",
    "ArchiveStream",
    "BINANCE_USDM_ARCHIVE",
    "BYBIT_TRADING_ARCHIVE",
    "binance_usdm_aggtrades_url",
    "bybit_trades_url",
    "fetch_official_archive_day",
    "fetch_official_archive_stream",
    "iter_days",
    "parse_binance_aggtrades_csv",
    "parse_bybit_trades_csv",
]
