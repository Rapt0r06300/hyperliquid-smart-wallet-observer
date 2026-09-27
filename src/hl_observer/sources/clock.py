"""Bounded exchange/server clock synchronization for replay-grade capture.

This module is pure and read-only. It never changes the system clock and refuses
to certify a venue timestamp when the measured offset is outside the configured
bound or the uncertainty is too large.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True, slots=True)
class ClockSample:
    local_send_ms: int
    local_receive_ms: int
    server_ms: int

    @property
    def round_trip_ms(self) -> int:
        return max(0, self.local_receive_ms - self.local_send_ms)

    @property
    def midpoint_local_ms(self) -> float:
        return (self.local_send_ms + self.local_receive_ms) / 2.0

    @property
    def offset_ms(self) -> float:
        return float(self.server_ms) - self.midpoint_local_ms

    @property
    def uncertainty_ms(self) -> float:
        return self.round_trip_ms / 2.0


@dataclass(frozen=True, slots=True)
class ClockSyncState:
    venue: str
    offset_ms: float
    uncertainty_ms: float
    sample_count: int
    synchronized: bool
    reason: str


class ClockSynchronizer:
    def __init__(
        self,
        venue: str,
        *,
        max_offset_ms: float = 250.0,
        max_uncertainty_ms: float = 500.0,
        min_samples: int = 3,
    ) -> None:
        self.venue = venue
        self.max_offset_ms = float(max_offset_ms)
        self.max_uncertainty_ms = float(max_uncertainty_ms)
        self.min_samples = max(1, int(min_samples))
        self._samples: list[ClockSample] = []

    def add_sample(self, sample: ClockSample) -> ClockSyncState:
        if sample.local_receive_ms < sample.local_send_ms:
            raise ValueError("clock sample receive time precedes send time")
        self._samples.append(sample)
        self._samples = self._samples[-31:]
        return self.state()

    def state(self) -> ClockSyncState:
        if not self._samples:
            return ClockSyncState(self.venue, 0.0, float("inf"), 0, False, "NO_SAMPLES")
        offsets = [sample.offset_ms for sample in self._samples]
        uncertainties = [sample.uncertainty_ms for sample in self._samples]
        offset = float(median(offsets))
        uncertainty = float(max(uncertainties))
        if len(self._samples) < self.min_samples:
            reason = "INSUFFICIENT_SAMPLES"
            synced = False
        elif uncertainty > self.max_uncertainty_ms:
            reason = "UNCERTAINTY_TOO_HIGH"
            synced = False
        elif abs(offset) > self.max_offset_ms:
            reason = "OFFSET_TOO_HIGH"
            synced = False
        else:
            reason = "SYNCHRONIZED"
            synced = True
        return ClockSyncState(
            self.venue, offset, uncertainty, len(self._samples), synced, reason
        )

    def normalize_server_timestamp(self, server_ms: int) -> int:
        state = self.state()
        if not state.synchronized:
            raise RuntimeError(f"clock not synchronized: {state.reason}")
        return int(round(float(server_ms) - state.offset_ms))


__all__ = ["ClockSample", "ClockSyncState", "ClockSynchronizer"]
