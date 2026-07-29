"""Append-only, replayable storage for market data observed by HyperSmart.

Each record preserves the raw payload and three distinct clocks:

* exchange timestamp: what the venue reported;
* receive timestamp: when HyperSmart received the frame;
* write timestamp: when the frame reached durable local storage.

The format is intentionally JSONL so a damaged line does not invalidate a
whole session. Rotation creates immutable gzip shards and never fabricates or
normalizes market events.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from hl_observer.realtime.feed_quality import FeedEventKind

SCHEMA_VERSION = "hypersmart.tick.v1"


def _raw_text(raw_payload: str | bytes | Mapping[str, Any] | list[Any]) -> str:
    if isinstance(raw_payload, bytes):
        return raw_payload.decode("utf-8", errors="replace")
    if isinstance(raw_payload, str):
        return raw_payload
    return json.dumps(
        raw_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class TickEnvelope:
    source_id: str
    channel: str
    instrument: str
    event_kind: FeedEventKind | str
    raw_payload: str | bytes | Mapping[str, Any] | list[Any]
    received_ts_ms: int
    exchange_ts_ms: int | None = None
    local_monotonic_ns: int | None = None
    connection_id: str | None = None
    sequence: int | None = None
    reconnect_count: int = 0
    gap_count: int = 0
    provenance: dict[str, Any] = field(default_factory=dict)
    parsed_summary: dict[str, Any] = field(default_factory=dict)
    written_ts_ms: int | None = None

    def as_record(self, *, written_ts_ms: int) -> dict[str, Any]:
        raw = _raw_text(self.raw_payload)
        kind = (
            self.event_kind.value
            if isinstance(self.event_kind, FeedEventKind)
            else str(self.event_kind)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "source_id": str(self.source_id),
            "channel": str(self.channel),
            "instrument": str(self.instrument),
            "event_kind": kind,
            "exchange_ts_ms": (
                None if self.exchange_ts_ms is None else int(self.exchange_ts_ms)
            ),
            "received_ts_ms": int(self.received_ts_ms),
            "written_ts_ms": int(
                self.written_ts_ms if self.written_ts_ms is not None else written_ts_ms
            ),
            "local_monotonic_ns": (
                None if self.local_monotonic_ns is None else int(self.local_monotonic_ns)
            ),
            "connection_id": self.connection_id,
            "sequence": None if self.sequence is None else int(self.sequence),
            "reconnect_count": int(self.reconnect_count),
            "gap_count": int(self.gap_count),
            "raw_sha256": _sha256(raw),
            "raw_payload": raw,
            "provenance": dict(self.provenance),
            "parsed_summary": dict(self.parsed_summary),
            "read_only": True,
            "real_execution": False,
        }


class TickDatasetWriter:
    """Durable JSONL writer with immutable gzip shard rotation."""

    def __init__(
        self,
        directory: Path | str,
        *,
        stream_name: str = "hyperliquid_market_ticks",
        rotate_bytes: int = 128 * 1024 * 1024,
        flush_every: int = 1,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.shards_directory = self.directory / "shards"
        self.shards_directory.mkdir(parents=True, exist_ok=True)
        self.stream_name = str(stream_name)
        self.rotate_bytes = max(1, int(rotate_bytes))
        self.flush_every = max(1, int(flush_every))
        self.current_path = self.directory / f"{self.stream_name}.current.jsonl"
        self.manifest_path = self.directory / f"{self.stream_name}.manifest.json"
        self.records_written = 0
        self.bytes_written = 0
        self.shards_written = 0
        self._first_received_ts_ms: int | None = None
        self._last_received_ts_ms: int | None = None

    def append(self, envelope: TickEnvelope) -> int:
        return self.append_batch((envelope,))

    def append_batch(self, envelopes: Iterable[TickEnvelope]) -> int:
        return len(self.append_batch_records(envelopes))

    def append_batch_records(self, envelopes: Iterable[TickEnvelope]) -> list[dict[str, Any]]:
        """Persist a batch and return the exact records that reached disk.

        Returning the durable records lets the canonical-event stage reference
        the real write timestamp instead of inventing an approximate one.
        """
        batch = list(envelopes)
        if not batch:
            return []
        written_ts_ms = int(time.time() * 1000)
        records: list[dict[str, Any]] = []
        lines: list[str] = []
        for envelope in batch:
            record = envelope.as_record(written_ts_ms=written_ts_ms)
            records.append(record)
            received_ts = int(record["received_ts_ms"])
            self._first_received_ts_ms = (
                received_ts
                if self._first_received_ts_ms is None
                else min(self._first_received_ts_ms, received_ts)
            )
            self._last_received_ts_ms = (
                received_ts
                if self._last_received_ts_ms is None
                else max(self._last_received_ts_ms, received_ts)
            )
            lines.append(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            )

        encoded = "".join(lines)
        with self.current_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        count = len(batch)
        self.records_written += count
        self.bytes_written += len(encoded.encode("utf-8"))
        if self.current_path.stat().st_size >= self.rotate_bytes:
            self.rotate()
        elif self.records_written % self.flush_every == 0:
            self._write_manifest()
        return records

    def rotate(self) -> Path | None:
        if not self.current_path.exists() or self.current_path.stat().st_size == 0:
            return None
        timestamp_ns = time.time_ns()
        first = self._first_received_ts_ms or 0
        last = self._last_received_ts_ms or first
        name = f"{self.stream_name}.{first}-{last}.{timestamp_ns}.jsonl.gz"
        final_path = self.shards_directory / name
        temporary_path = final_path.with_suffix(final_path.suffix + ".tmp")
        with self.current_path.open("rb") as source, gzip.open(temporary_path, "wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        os.replace(temporary_path, final_path)
        self.current_path.write_text("", encoding="utf-8")
        self.shards_written += 1
        self._first_received_ts_ms = None
        self._last_received_ts_ms = None
        self._write_manifest()
        return final_path

    def iter_records(self) -> Iterator[dict[str, Any]]:
        paths: list[Path] = sorted(self.shards_directory.glob(f"{self.stream_name}.*.jsonl.gz"))
        for path in paths:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                yield from self._iter_handle(handle)
        if self.current_path.exists():
            with self.current_path.open(encoding="utf-8") as handle:
                yield from self._iter_handle(handle)

    @staticmethod
    def _iter_handle(handle: Iterable[str]) -> Iterator[dict[str, Any]]:
        for line in handle:
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(record, dict) and record.get("schema_version") == SCHEMA_VERSION:
                yield record

    def stats(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stream_name": self.stream_name,
            "current_path": str(self.current_path),
            "shards_directory": str(self.shards_directory),
            "records_written": self.records_written,
            "bytes_written": self.bytes_written,
            "shards_written": self.shards_written,
            "first_received_ts_ms": self._first_received_ts_ms,
            "last_received_ts_ms": self._last_received_ts_ms,
            "read_only": True,
            "real_execution": False,
        }

    def _write_manifest(self) -> None:
        payload = {
            **self.stats(),
            "updated_at_ms": int(time.time() * 1000),
            "immutable_shards": [
                path.name
                for path in sorted(
                    self.shards_directory.glob(f"{self.stream_name}.*.jsonl.gz")
                )
            ],
        }
        temporary = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.manifest_path)


__all__ = ["SCHEMA_VERSION", "TickDatasetWriter", "TickEnvelope"]
