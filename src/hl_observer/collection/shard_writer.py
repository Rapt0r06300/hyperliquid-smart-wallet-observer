"""Immutable gzip JSONL shard writer for heavy replay/backtest datasets."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ShardManifest:
    schema: str
    venue: str
    family: str
    symbol: str
    collector_version: str
    file_name: str
    sha256: str
    bytes: int
    event_count: int
    start_receive_ts_ms: int | None
    end_receive_ts_ms: int | None
    start_exchange_ts_ms: int | None
    end_exchange_ts_ms: int | None
    quality_status: str
    read_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ImmutableGzipShardWriter:
    """Write one bounded immutable shard and return its cryptographic manifest."""

    def __init__(
        self,
        path: str | Path,
        *,
        venue: str,
        family: str,
        symbol: str,
        collector_version: str,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.venue = str(venue).strip().lower()
        self.family = str(family).strip().lower()
        self.symbol = str(symbol).strip().upper()
        self.collector_version = str(collector_version)
        self._handle = gzip.open(self.path, "wt", encoding="utf-8", newline="\n")
        self.event_count = 0
        self._receive_times: list[int] = []
        self._exchange_times: list[int] = []
        self._closed = False

    def append(self, record: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("shard is already closed")
        recv = _timestamp(
            record.get("receive_ts_ms", record.get("received_ts_ms", record.get("recv_wall_ts_ms")))
        )
        exchange = _timestamp(record.get("exchange_ts_ms"))
        if recv is None:
            raise ValueError("receive timestamp is required for replay-safe shards")
        if exchange is None:
            raise ValueError("exchange timestamp is required for replay-safe shards")
        line = json.dumps(
            dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        self._handle.write(line + "\n")
        self.event_count += 1
        self._receive_times.append(recv)
        self._exchange_times.append(exchange)

    def close(self, *, quality_status: str = "QUARANTINE") -> ShardManifest:
        if self._closed:
            raise RuntimeError("shard is already closed")
        self._handle.flush()
        self._handle.close()
        self._closed = True
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return ShardManifest(
            schema="alina.dataset_shard.v2",
            venue=self.venue,
            family=self.family,
            symbol=self.symbol,
            collector_version=self.collector_version,
            file_name=self.path.name,
            sha256=digest.hexdigest(),
            bytes=os.path.getsize(self.path),
            event_count=self.event_count,
            start_receive_ts_ms=min(self._receive_times) if self._receive_times else None,
            end_receive_ts_ms=max(self._receive_times) if self._receive_times else None,
            start_exchange_ts_ms=min(self._exchange_times) if self._exchange_times else None,
            end_exchange_ts_ms=max(self._exchange_times) if self._exchange_times else None,
            quality_status=str(quality_status).upper(),
        )


def _timestamp(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["ImmutableGzipShardWriter", "ShardManifest"]
