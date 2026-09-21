"""Fail-closed feed-integrity and clock-synchronisation primitives.

These helpers are deliberately network-free. Venue adapters feed them the timestamps
and sequence identifiers observed on public market-data streams. Missing evidence is
kept missing; it is never replaced with synthetic zeroes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ClockSyncSample:
    venue: str
    server_ts_ms: int
    send_wall_ts_ms: int
    receive_wall_ts_ms: int
    rtt_ms: float
    offset_ms: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_clock_sync(
    *,
    venue: str,
    server_ts_ms: int,
    send_wall_ts_ms: int,
    receive_wall_ts_ms: int,
) -> ClockSyncSample:
    """Estimate server clock offset using the request midpoint.

    The estimate includes network asymmetry, so it is evidence rather than a claim of
    perfect clock synchronisation. Negative RTTs are rejected.
    """
    sent = int(send_wall_ts_ms)
    received = int(receive_wall_ts_ms)
    if received < sent:
        raise ValueError("receive_wall_ts_ms cannot precede send_wall_ts_ms")
    server = int(server_ts_ms)
    midpoint = (sent + received) / 2.0
    return ClockSyncSample(
        venue=str(venue).strip().lower(),
        server_ts_ms=server,
        send_wall_ts_ms=sent,
        receive_wall_ts_ms=received,
        rtt_ms=float(received - sent),
        offset_ms=float(server - midpoint),
    )


@dataclass(slots=True)
class FeedIntegrityState:
    """Incremental integrity evidence for one venue/symbol/channel stream."""

    strict_consecutive_sequence: bool = False
    future_skew_tolerance_ms: int = 2_000
    last_sequence: int | None = None
    last_exchange_ts_ms: int | None = None
    last_receive_ts_ms: int | None = None
    last_receive_mono_ns: int | None = None
    messages: int = 0
    duplicates: int = 0
    gaps: int = 0
    regressions: int = 0
    exchange_time_regressions: int = 0
    receive_time_regressions: int = 0
    monotonic_regressions: int = 0
    missing_exchange_ts: int = 0
    missing_receive_ts: int = 0
    future_skew_violations: int = 0
    reconnects: int = 0

    def observe(
        self,
        *,
        sequence: int | None,
        exchange_ts_ms: int | None,
        receive_ts_ms: int | None,
        receive_mono_ns: int | None = None,
        prev_sequence: int | None = None,
        reset: bool = False,
    ) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        self.messages += 1

        if reset:
            self.reconnects += 1
            self.last_sequence = None
            self.last_exchange_ts_ms = None
            self.last_receive_ts_ms = None
            self.last_receive_mono_ns = None

        seq = None if sequence is None else int(sequence)
        prev = None if prev_sequence is None else int(prev_sequence)
        if seq is not None and self.last_sequence is not None:
            if seq == self.last_sequence:
                self.duplicates += 1
                reasons.append("DUPLICATE_SEQUENCE")
            elif seq < self.last_sequence:
                self.regressions += 1
                reasons.append("SEQUENCE_REGRESSION")
            elif prev is not None and prev not in {self.last_sequence, -1}:
                self.gaps += 1
                reasons.append("SEQUENCE_GAP")
            elif self.strict_consecutive_sequence and seq != self.last_sequence + 1:
                self.gaps += max(1, seq - self.last_sequence - 1)
                reasons.append("SEQUENCE_GAP")
        elif prev is not None and self.last_sequence is not None and prev not in {
            self.last_sequence,
            -1,
        }:
            self.gaps += 1
            reasons.append("SEQUENCE_GAP")

        ex = None if exchange_ts_ms is None else int(exchange_ts_ms)
        recv = None if receive_ts_ms is None else int(receive_ts_ms)
        mono = None if receive_mono_ns is None else int(receive_mono_ns)

        if ex is None:
            self.missing_exchange_ts += 1
            reasons.append("MISSING_EXCHANGE_TIMESTAMP")
        elif self.last_exchange_ts_ms is not None and ex < self.last_exchange_ts_ms:
            self.exchange_time_regressions += 1
            reasons.append("EXCHANGE_TIME_REGRESSION")

        if recv is None:
            self.missing_receive_ts += 1
            reasons.append("MISSING_RECEIVE_TIMESTAMP")
        elif self.last_receive_ts_ms is not None and recv < self.last_receive_ts_ms:
            self.receive_time_regressions += 1
            reasons.append("RECEIVE_TIME_REGRESSION")

        if mono is not None and self.last_receive_mono_ns is not None and mono < self.last_receive_mono_ns:
            self.monotonic_regressions += 1
            reasons.append("MONOTONIC_TIME_REGRESSION")

        if ex is not None and recv is not None and ex - recv > self.future_skew_tolerance_ms:
            self.future_skew_violations += 1
            reasons.append("EXCHANGE_TIMESTAMP_IN_FUTURE")

        if seq is not None and "SEQUENCE_REGRESSION" not in reasons:
            self.last_sequence = seq
        if ex is not None and "EXCHANGE_TIME_REGRESSION" not in reasons:
            self.last_exchange_ts_ms = ex
        if recv is not None and "RECEIVE_TIME_REGRESSION" not in reasons:
            self.last_receive_ts_ms = recv
        if mono is not None and "MONOTONIC_TIME_REGRESSION" not in reasons:
            self.last_receive_mono_ns = mono

        fatal = {
            "SEQUENCE_GAP",
            "SEQUENCE_REGRESSION",
            "EXCHANGE_TIME_REGRESSION",
            "RECEIVE_TIME_REGRESSION",
            "MONOTONIC_TIME_REGRESSION",
            "MISSING_RECEIVE_TIMESTAMP",
            "EXCHANGE_TIMESTAMP_IN_FUTURE",
        }
        return not any(reason in fatal for reason in reasons), tuple(dict.fromkeys(reasons))

    @property
    def clean(self) -> bool:
        return not any(
            (
                self.gaps,
                self.regressions,
                self.exchange_time_regressions,
                self.receive_time_regressions,
                self.monotonic_regressions,
                self.missing_receive_ts,
                self.future_skew_violations,
            )
        )

    def as_dict(self) -> dict[str, int | bool | None]:
        return {
            "messages": self.messages,
            "duplicates": self.duplicates,
            "gaps": self.gaps,
            "regressions": self.regressions,
            "exchange_time_regressions": self.exchange_time_regressions,
            "receive_time_regressions": self.receive_time_regressions,
            "monotonic_regressions": self.monotonic_regressions,
            "missing_exchange_ts": self.missing_exchange_ts,
            "missing_receive_ts": self.missing_receive_ts,
            "future_skew_violations": self.future_skew_violations,
            "reconnects": self.reconnects,
            "last_sequence": self.last_sequence,
            "last_exchange_ts_ms": self.last_exchange_ts_ms,
            "last_receive_ts_ms": self.last_receive_ts_ms,
            "clean": self.clean,
        }


__all__ = [
    "ClockSyncSample",
    "FeedIntegrityState",
    "estimate_clock_sync",
]
