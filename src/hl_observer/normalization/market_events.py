"""Canonical, replayable market events derived from durable tick records.

Canonical events are not a cleaned-up substitute for raw data. They retain a
cryptographic reference to the exact raw tick record and use
``observable_at_ms`` (local durable write time) as the earliest time a replay
may consume them. This prevents exchange timestamps from leaking future
knowledge into backtests.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hl_observer.core.causal_time import causal_timestamp_from_record

CANONICAL_SCHEMA_VERSION = "hypersmart.market_event.v1"


@dataclass(frozen=True, slots=True)
class CanonicalMarketEvent:
    event_id: str
    event_type: str
    source_tick_ref: str
    source_id: str
    channel: str
    instrument: str
    connection_id: str | None
    sequence: int | None
    recv_mono_ns: int | None
    exchange_ts_ms: int | None
    received_ts_ms: int
    written_ts_ms: int
    observable_at_ms: int
    raw_sha256: str
    raw_payload: Any
    parsed_summary: Mapping[str, Any]
    provenance: Mapping[str, Any]
    feed_quality_score: float | None
    data_gate_ready: bool
    signal_eligible: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANONICAL_SCHEMA_VERSION,
            **asdict(self),
            "recv_wall_ts_ms": self.received_ts_ms,
            "write_wall_ts_ms": self.written_ts_ms,
            "parsed_summary": dict(self.parsed_summary),
            "provenance": dict(self.provenance),
            "read_only": True,
            "real_execution": False,
        }


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    event: CanonicalMarketEvent | None
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.event is not None


def canonicalize_tick_record(record: Mapping[str, Any]) -> CanonicalizationResult:
    """Validate a durable tick record and make it signal-safe or reject it."""
    reasons: list[str] = []
    if record.get("schema_version") != "hypersmart.tick.v1":
        reasons.append("UNSUPPORTED_TICK_SCHEMA")
    source_id = str(record.get("source_id") or "")
    channel = str(record.get("channel") or "")
    instrument = str(record.get("instrument") or "")
    raw_payload_text = str(record.get("raw_payload") or "")
    raw_sha = str(record.get("raw_sha256") or "")
    if not source_id or not channel or not instrument:
        reasons.append("MISSING_SOURCE_IDENTITY")
    if hashlib.sha256(raw_payload_text.encode("utf-8")).hexdigest() != raw_sha:
        reasons.append("RAW_HASH_MISMATCH")

    try:
        clock = causal_timestamp_from_record(record)
        if clock.recv_wall_ts_ms is None or clock.write_wall_ts_ms is None:
            raise ValueError("missing durable wall clock")
        received_ts_ms = clock.recv_wall_ts_ms
        written_ts_ms = clock.write_wall_ts_ms
    except (TypeError, ValueError):
        reasons.append("MISSING_LOCAL_TIMESTAMPS")
        received_ts_ms = written_ts_ms = 0
    if written_ts_ms < received_ts_ms:
        reasons.append("WRITE_BEFORE_RECEIVE")

    parsed_summary = record.get("parsed_summary")
    if not isinstance(parsed_summary, Mapping):
        parsed_summary = {}
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    if provenance.get("access") != "read_only":
        reasons.append("PROVENANCE_NOT_READ_ONLY")

    control_event = channel == "connection"
    quality_score, gate_ready = _quality_from_summary(
        channel=channel,
        instrument=instrument,
        summary=parsed_summary,
    )
    if not control_event and not gate_ready:
        reasons.append("DATA_QUALITY_GATE_NOT_READY")
    if reasons:
        return CanonicalizationResult(None, tuple(dict.fromkeys(reasons)))

    try:
        raw_payload = json.loads(raw_payload_text)
    except (TypeError, ValueError):
        raw_payload = raw_payload_text
    event_type = _event_type(channel, str(record.get("event_kind") or "EVENT"))
    source_tick_ref = "tick:%s:%d" % (raw_sha, received_ts_ms)
    event_material = "|".join(
        (
            source_tick_ref,
            channel,
            instrument,
            str(received_ts_ms),
            str(written_ts_ms),
        )
    )
    event_id = "market:" + hashlib.sha256(event_material.encode("utf-8")).hexdigest()
    event = CanonicalMarketEvent(
        event_id=event_id,
        event_type=event_type,
        source_tick_ref=source_tick_ref,
        source_id=source_id,
        channel=channel,
        instrument=instrument,
        connection_id=clock.connection_id,
        sequence=clock.sequence,
        recv_mono_ns=clock.recv_mono_ns,
        exchange_ts_ms=(
            None
            if record.get("exchange_ts_ms") is None
            else int(record["exchange_ts_ms"])
        ),
        received_ts_ms=received_ts_ms,
        written_ts_ms=written_ts_ms,
        observable_at_ms=max(received_ts_ms, written_ts_ms),
        raw_sha256=raw_sha,
        raw_payload=raw_payload,
        parsed_summary=dict(parsed_summary),
        provenance=dict(provenance),
        feed_quality_score=quality_score,
        data_gate_ready=True if control_event else gate_ready,
        signal_eligible=(
            not control_event
            and channel in {"bbo", "l2Book", "trades"}
            and gate_ready
        ),
    )
    return CanonicalizationResult(event, ())


def _quality_from_summary(
    *,
    channel: str,
    instrument: str,
    summary: Mapping[str, Any],
) -> tuple[float | None, bool]:
    if channel == "trades":
        by_coin = summary.get("quality_by_coin")
        if isinstance(by_coin, Mapping):
            quality = by_coin.get(instrument)
            if isinstance(quality, Mapping):
                return _to_optional_float(quality.get("feed_quality_score")), bool(
                    quality.get("data_gate_ready")
                )
    return _to_optional_float(summary.get("feed_quality_score")), bool(
        summary.get("data_gate_ready")
    )


def _to_optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_type(channel: str, event_kind: str) -> str:
    if channel == "bbo":
        return "BBO_SNAPSHOT"
    if channel == "l2Book":
        return "L2_BOOK_SNAPSHOT"
    if channel == "trades":
        return "PUBLIC_TRADE_BATCH"
    if channel == "connection":
        return "FEED_%s" % event_kind.upper()
    return "SOURCE_EVENT"


class CanonicalEventWriter:
    """Append-only canonical event ledger with stable deduplication."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self.written = 0
        self.duplicates = 0

    def append(self, events: Iterable[CanonicalMarketEvent]) -> int:
        rows: list[str] = []
        for event in events:
            if event.event_id in self._seen:
                self.duplicates += 1
                continue
            self._seen.add(event.event_id)
            rows.append(
                json.dumps(
                    event.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            )
        if not rows:
            return 0
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(rows))
            handle.flush()
            os.fsync(handle.fileno())
        self.written += len(rows)
        return len(rows)

    def iter_events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if (
                    isinstance(row, dict)
                    and row.get("schema_version") == CANONICAL_SCHEMA_VERSION
                ):
                    yield row


__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "CanonicalEventWriter",
    "CanonicalMarketEvent",
    "CanonicalizationResult",
    "canonicalize_tick_record",
]
