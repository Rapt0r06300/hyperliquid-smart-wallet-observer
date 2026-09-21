"""Build Alina dataset V2 manifests by inspecting immutable TickDataset shards."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def build_manifest_from_tick_shard(
    shard_path: str | Path,
    *,
    collector_version: str,
    reconciliation_status: str = "UNVERIFIED",
    required_channels: Iterable[str] = (),
    cost_model_applicable: bool = False,
    cost_model_ready: bool = False,
) -> dict[str, Any]:
    path = Path(shard_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    sources: set[str] = set()
    channels: set[str] = set()
    instruments: set[str] = set()
    receive_times: list[int] = []
    exchange_times: list[int] = []
    identities: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    gap_count = 0
    regression_count = 0
    missing_timestamp_count = 0
    missing_monotonic_count = 0
    desync_count = 0
    event_count = 0
    public_only = True
    authenticated_false = True
    authenticated_explicit = True
    real_execution_false = True
    last_exchange: dict[tuple[str, str, str], int] = {}
    last_receive: dict[tuple[str, str, str], int] = {}
    last_mono: dict[tuple[str, str, str], int] = {}
    last_sequence: dict[tuple[str, str, str], int] = {}
    connection_ids: set[str] = set()
    transports: set[str] = set()
    receive_exchange_deltas_ms: list[float] = []
    transport_rtt_ms: list[float] = []
    clock_offsets_ms: list[float] = []
    reconnect_count_max = 0
    gap_counter_values: list[int] = []
    reconnect_counter_values: list[int] = []

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            event_count += 1
            source = str(record.get("source_id") or "")
            channel = str(record.get("channel") or "")
            instrument = str(record.get("instrument") or "")
            sources.add(source)
            channels.add(channel)
            instruments.add(instrument)
            key = (source, channel, instrument)

            receive = _int(record.get("received_ts_ms", record.get("recv_wall_ts_ms")))
            exchange = _int(record.get("exchange_ts_ms"))
            mono = _int(record.get("local_monotonic_ns", record.get("recv_mono_ns")))
            if receive is None or exchange is None:
                missing_timestamp_count += 1
            if mono is None:
                missing_monotonic_count += 1
            connection_id = str(record.get("connection_id") or "")
            if connection_id:
                connection_ids.add(connection_id)
            record_gap_counter = _int(record.get("gap_count"))
            if record_gap_counter is not None:
                gap_counter_values.append(record_gap_counter)
            record_reconnect_counter = _int(record.get("reconnect_count"))
            if record_reconnect_counter is not None:
                reconnect_counter_values.append(record_reconnect_counter)
                reconnect_count_max = max(
                    reconnect_count_max,
                    record_reconnect_counter,
                )
            if receive is not None and exchange is not None:
                receive_exchange_deltas_ms.append(float(receive - exchange))
            if receive is not None:
                receive_times.append(receive)
                previous = last_receive.get(key)
                if previous is not None and receive < previous:
                    regression_count += 1
                last_receive[key] = max(previous or receive, receive)
            if exchange is not None:
                exchange_times.append(exchange)
                previous = last_exchange.get(key)
                if previous is not None and exchange < previous:
                    regression_count += 1
                last_exchange[key] = max(previous or exchange, exchange)
            if mono is not None:
                previous = last_mono.get(key)
                if previous is not None and mono < previous:
                    regression_count += 1
                last_mono[key] = max(previous or mono, mono)

            identity = (
                source,
                channel,
                instrument,
                exchange,
                record.get("sequence"),
                record.get("raw_sha256"),
            )
            if identity in identities:
                duplicate_count += 1
            else:
                identities.add(identity)

            if str(record.get("event_kind") or "").upper() == "GAP":
                gap_count += 1
            summary = record.get("parsed_summary")
            sequence = _int(record.get("sequence"))
            previous_sequence = last_sequence.get(key)
            sequence_gap = False
            if isinstance(summary, Mapping):
                if str(summary.get("quality") or "").upper() == "DESYNC":
                    desync_count += 1
                if summary.get("needs_resnapshot") is True:
                    desync_count += 1

                # Venue-provided continuity evidence. This is intentionally
                # limited to streams whose protocol publishes predecessor IDs.
                reported_previous = _int(
                    summary.get(
                        "prev_sequence",
                        summary.get("previous_update_id"),
                    )
                )
                first_update = _int(summary.get("first_update_id"))
                if channel == "l2Book" and previous_sequence is not None:
                    if (
                        reported_previous is not None
                        and reported_previous not in {-1, previous_sequence}
                    ):
                        sequence_gap = True
                    if (
                        first_update is not None
                        and first_update > previous_sequence + 1
                    ):
                        sequence_gap = True
            if sequence_gap:
                gap_count += 1
            if sequence is not None:
                if previous_sequence is not None and sequence < previous_sequence:
                    regression_count += 1
                if previous_sequence is None or sequence > previous_sequence:
                    last_sequence[key] = sequence

            provenance = record.get("provenance")
            if not isinstance(provenance, Mapping):
                public_only = False
                authenticated_false = False
                authenticated_explicit = False
            else:
                public_only = public_only and str(provenance.get("access") or "").lower() in {
                    "read_only",
                    "public_read_only",
                }
                transport = str(provenance.get("transport") or "")
                if transport:
                    transports.add(transport)
                if "authenticated" not in provenance:
                    authenticated_explicit = False
                authenticated = provenance.get("authenticated")
                authenticated_false = authenticated_false and authenticated is False
            if isinstance(summary, Mapping):
                rtt = _float(summary.get("transport_rtt_ms"))
                if rtt is not None:
                    transport_rtt_ms.append(rtt)
                offset = _float(summary.get("clock_offset_ms"))
                if offset is not None:
                    clock_offsets_ms.append(offset)
            real_execution_false = real_execution_false and record.get("real_execution") is False

    if event_count <= 0:
        raise ValueError("empty tick shard")
    if len(sources) != 1 or len(channels) != 1 or len(instruments) != 1:
        raise ValueError(
            "V2 export requires one source/channel/instrument per shard; "
            "use PartitionedTickDatasetWriter"
        )

    if gap_counter_values:
        gap_count += max(gap_counter_values) - min(gap_counter_values)
    reconnect_delta = (
        max(reconnect_counter_values) - min(reconnect_counter_values)
        if reconnect_counter_values
        else 0
    )

    source = next(iter(sources))
    channel = next(iter(channels))
    instrument = next(iter(instruments))
    start = min(receive_times) if receive_times else 0
    end = max(receive_times) if receive_times else 0
    sha256 = digest.hexdigest()
    dataset_id = _dataset_id(source, channel, instrument, start, end, sha256)

    return {
        "schema": "alina.shard_manifest.v2",
        "dataset_id": dataset_id,
        "family": channel,
        "venue": _venue(source),
        "symbol": instrument,
        "start_ts_ms": start,
        "end_ts_ms": end,
        "sha256": sha256,
        "bytes": path.stat().st_size,
        "event_count": event_count,
        "collector_version": str(collector_version),
        "source": source,
        "quality_status": "PARTIAL",
        "release_asset": path.name,
        "asset_verified": False,
        "provenance": {
            "public_data_only": bool(public_only),
            "authenticated": (
                False if authenticated_false and authenticated_explicit else None
            ),
            "real_execution": not bool(real_execution_false),
            "transports": sorted(transports),
        },
        "integrity": {
            "gap_count": gap_count,
            "duplicate_count": duplicate_count,
            "regression_count": regression_count,
            "missing_timestamp_count": missing_timestamp_count,
            "missing_monotonic_count": missing_monotonic_count,
            "desync_count": desync_count,
            "duplicates_deduped": duplicate_count == 0,
        },
        "synchronization": {
            "first_exchange_ts_ms": min(exchange_times) if exchange_times else None,
            "last_exchange_ts_ms": max(exchange_times) if exchange_times else None,
            "connection_ids": sorted(connection_ids),
            "connection_count": len(connection_ids),
            "max_reconnect_count": reconnect_count_max,
            "reconnect_delta": reconnect_delta,
            "receive_minus_exchange_ms": _stats(receive_exchange_deltas_ms),
            "transport_rtt_ms": _stats(transport_rtt_ms),
            "clock_offset_ms": _stats(clock_offsets_ms),
        },
        "reconciliation": {
            "status": str(reconciliation_status or "UNVERIFIED").upper()
        },
        "required_channels": sorted({str(value) for value in required_channels if str(value)}),
        "observed_channels": [channel],
        "cost_model": {
            "applicable": bool(cost_model_applicable),
            "ready": bool(cost_model_ready),
        },
        "validation_allowed": False,
        "proof_of_pnl_allowed": False,
    }


def write_manifest(manifest: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _dataset_id(
    source: str,
    channel: str,
    instrument: str,
    start: int,
    end: int,
    sha256: str,
) -> str:
    raw = "-".join(
        (
            _slug(source),
            _slug(channel),
            _slug(instrument),
            str(int(start)),
            str(int(end)),
            sha256[:12],
        )
    )
    return raw[:220]


def _venue(source: str) -> str:
    value = str(source).lower()
    for venue in ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget"):
        if venue in value:
            return venue
    return "unknown"


def _slug(value: object) -> str:
    return "".join(
        char.lower() if char.isalnum() else "-"
        for char in str(value or "")
    ).strip("-") or "unknown"


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _stats(values: Iterable[float]) -> dict[str, float | int | None]:
    rows = sorted(float(value) for value in values)
    if not rows:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    def percentile(fraction: float) -> float:
        index = min(len(rows) - 1, max(0, int(round((len(rows) - 1) * fraction))))
        return rows[index]
    return {
        "count": len(rows),
        "min": round(rows[0], 6),
        "p50": round(percentile(0.50), 6),
        "p95": round(percentile(0.95), 6),
        "max": round(rows[-1], 6),
    }


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["build_manifest_from_tick_shard", "write_manifest"]
