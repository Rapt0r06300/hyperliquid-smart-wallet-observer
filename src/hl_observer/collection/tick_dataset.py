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
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.collection.collecte_fiable import remplacer_avec_reprises
from hl_observer.realtime.feed_quality import FeedEventKind

SCHEMA_VERSION = "hypersmart.tick.v1"


def _windows_io_path(path: Path) -> Path:
    """Use Win32 extended paths before nested shard names approach MAX_PATH."""
    path = Path(path)
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    # Rotation appends a long timestamped filename and a sidecar suffix.
    # Prefix the directory early enough that the complete leaf stays below
    # the legacy 260-character Win32 limit.
    if absolute.startswith("\\\\?\\") or len(absolute) < 160:
        return path
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _venue_from_source(source_id: str) -> str | None:
    lowered = str(source_id).lower()
    for venue in (
        "hyperliquid", "binance", "bybit", "okx", "bitget", "gate",
        "deribit", "kraken", "coinbase", "htx",
    ):
        if venue in lowered:
            return venue
    return None


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
    venue: str | None = None
    matching_engine_ts_ms: int | None = None
    server_ts_ms: int | None = None
    clock_probe_rtt_ms: float | None = None
    observed_clock_offset_ms: float | None = None
    clock_offset_uncertainty_ms: float | None = None

    def as_record(self, *, written_ts_ms: int) -> dict[str, Any]:
        raw = _raw_text(self.raw_payload)
        provenance = dict(self.provenance)
        summary = dict(self.parsed_summary)
        kind = (
            self.event_kind.value
            if isinstance(self.event_kind, FeedEventKind)
            else str(self.event_kind)
        )
        write_wall_ts_ms = int(
            self.written_ts_ms if self.written_ts_ms is not None else written_ts_ms
        )
        recv_mono_ns = (
            None if self.local_monotonic_ns is None else int(self.local_monotonic_ns)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "source_id": str(self.source_id),
            "venue": self.venue or provenance.get("venue") or _venue_from_source(self.source_id),
            "channel": str(self.channel),
            "instrument": str(self.instrument),
            "event_kind": kind,
            "exchange_ts_ms": (
                None if self.exchange_ts_ms is None else int(self.exchange_ts_ms)
            ),
            "matching_engine_ts_ms": (
                None
                if self.matching_engine_ts_ms is None
                and summary.get("matching_engine_ts_ms") is None
                else int(
                    self.matching_engine_ts_ms
                    if self.matching_engine_ts_ms is not None
                    else summary["matching_engine_ts_ms"]
                )
            ),
            "server_ts_ms": (
                None
                if self.server_ts_ms is None and summary.get("clock_probe_server_ts_ms") is None
                else int(
                    self.server_ts_ms
                    if self.server_ts_ms is not None
                    else summary["clock_probe_server_ts_ms"]
                )
            ),
            "received_ts_ms": int(self.received_ts_ms),
            "written_ts_ms": write_wall_ts_ms,
            "local_monotonic_ns": recv_mono_ns,
            # Canonical V2 names. Legacy aliases above remain replay-compatible.
            "recv_wall_ts_ms": int(self.received_ts_ms),
            "recv_mono_ns": recv_mono_ns,
            "write_wall_ts_ms": write_wall_ts_ms,
            "connection_id": self.connection_id,
            "sequence": None if self.sequence is None else int(self.sequence),
            "clock_probe_rtt_ms": (
                None
                if self.clock_probe_rtt_ms is None and summary.get("clock_probe_rtt_ms") is None
                else float(
                    self.clock_probe_rtt_ms
                    if self.clock_probe_rtt_ms is not None
                    else summary["clock_probe_rtt_ms"]
                )
            ),
            "observed_clock_offset_ms": (
                None
                if self.observed_clock_offset_ms is None and summary.get("clock_offset_ms") is None
                else float(
                    self.observed_clock_offset_ms
                    if self.observed_clock_offset_ms is not None
                    else summary["clock_offset_ms"]
                )
            ),
            "clock_offset_uncertainty_ms": (
                None
                if self.clock_offset_uncertainty_ms is None
                else float(self.clock_offset_uncertainty_ms)
            ),
            "reconnect_count": int(self.reconnect_count),
            "gap_count": int(self.gap_count),
            "raw_sha256": _sha256(raw),
            "raw_payload": raw,
            "provenance": provenance,
            "parsed_summary": summary,
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
        manifest_interval_s: float = 0.0,
    ) -> None:
        self.directory = _windows_io_path(Path(directory))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.shards_directory = self.directory / "shards"
        self.shards_directory.mkdir(parents=True, exist_ok=True)
        self.stream_name = str(stream_name)
        self.rotate_bytes = max(1, int(rotate_bytes))
        self.flush_every = max(1, int(flush_every))
        self.manifest_interval_s = max(0.0, float(manifest_interval_s))
        self._last_manifest_write_ns = 0
        self.current_path = self.directory / f"{self.stream_name}.current.jsonl"
        self.manifest_path = self.directory / f"{self.stream_name}.manifest.json"
        self.records_written = 0
        self.bytes_written = 0
        self.shards_written = 0
        self._current_records = 0
        self._records_since_manifest = 0
        self._first_received_ts_ms: int | None = None
        self._last_received_ts_ms: int | None = None

    def append(self, envelope: TickEnvelope) -> int:
        return self.append_batch((envelope,))

    def append_batch(self, envelopes: Iterable[TickEnvelope]) -> int:
        result = self._append_batch(envelopes, retain_records=False)
        assert isinstance(result, int)
        return result

    def append_batch_records(self, envelopes: Iterable[TickEnvelope]) -> list[dict[str, Any]]:
        """Persist a batch and return the exact records that reached disk.

        Returning the durable records lets the canonical-event stage reference
        the real write timestamp instead of inventing an approximate one.
        """
        result = self._append_batch(envelopes, retain_records=True)
        assert isinstance(result, list)
        return result

    def _append_batch(
        self,
        envelopes: Iterable[TickEnvelope],
        *,
        retain_records: bool,
    ) -> list[dict[str, Any]] | int:
        batch = list(envelopes)
        if not batch:
            return [] if retain_records else 0
        written_ts_ms = int(time.time() * 1000)
        records: list[dict[str, Any]] | None = [] if retain_records else None
        lines: list[str] = []
        for envelope in batch:
            record = envelope.as_record(written_ts_ms=written_ts_ms)
            if records is not None:
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
        self._current_records += count
        self._records_since_manifest += count
        self.bytes_written += len(encoded.encode("utf-8"))
        if self.current_path.stat().st_size >= self.rotate_bytes:
            self.rotate()
        else:
            now_ns = time.monotonic_ns()
            interval_due = (
                self.manifest_interval_s > 0
                and now_ns - self._last_manifest_write_ns
                >= int(self.manifest_interval_s * 1_000_000_000)
            )
            if (
                self._records_since_manifest >= self.flush_every
                or (
                    self.manifest_interval_s > 0
                    and not self.manifest_path.is_file()
                )
                or interval_due
            ):
                self._write_manifest()
                self._records_since_manifest = 0
        return records if records is not None else count

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
        remplacer_avec_reprises(temporary_path, final_path)
        shard_manifest = {
            "schema_version": "alina.tick_shard_manifest.v2",
            "stream_name": self.stream_name,
            "file_name": final_path.name,
            "sha256": _sha256_file(final_path),
            "bytes": final_path.stat().st_size,
            "event_count": self._current_records,
            "first_received_ts_ms": self._first_received_ts_ms,
            "last_received_ts_ms": self._last_received_ts_ms,
            "read_only": True,
            "real_execution": False,
        }
        sidecar = final_path.with_name(final_path.name + ".manifest.json")
        temporary_sidecar = sidecar.with_suffix(sidecar.suffix + ".tmp")
        temporary_sidecar.write_text(
            json.dumps(shard_manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        remplacer_avec_reprises(temporary_sidecar, sidecar)

        self.current_path.write_text("", encoding="utf-8")
        self.shards_written += 1
        self._current_records = 0
        self._first_received_ts_ms = None
        self._last_received_ts_ms = None
        self._write_manifest()
        self._records_since_manifest = 0
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
            "manifest_interval_s": self.manifest_interval_s,
            "current_path": str(self.current_path),
            "shards_directory": str(self.shards_directory),
            "records_written": self.records_written,
            "bytes_written": self.bytes_written,
            "shards_written": self.shards_written,
            "current_records": self._current_records,
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
            "immutable_shard_manifests": [
                path.name
                for path in sorted(
                    self.shards_directory.glob(
                        f"{self.stream_name}.*.jsonl.gz.manifest.json"
                    )
                )
            ],
        }
        temporary = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        remplacer_avec_reprises(temporary, self.manifest_path)
        self._last_manifest_write_ns = time.monotonic_ns()


__all__ = ["SCHEMA_VERSION", "TickDatasetWriter", "TickEnvelope"]
