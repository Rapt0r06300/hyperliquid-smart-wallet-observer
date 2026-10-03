"""Stateful market-feed validation and synchronization gates.

The gate is deliberately independent from trading logic. It answers one
question only: can a consumer trust the current local representation of this
feed?

Channel semantics matter:

* ``FULL_SNAPSHOT`` replaces the complete state on every message (Hyperliquid
  ``l2Book`` and ``bbo``).
* ``SNAPSHOT_THEN_INCREMENTAL`` requires a baseline snapshot before updates.
* ``EVENT_STREAM`` carries independent events such as public trades.

No network or execution code lives in this module.
"""
from __future__ import annotations

import math
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from hl_observer.realtime.event_identity import canonicalize_frame
from hl_observer.realtime.feed_quality_primitives import (
    _normalise_levels,
    _percentile,
    stable_event_id,
)


class FeedMode(str, Enum):
    FULL_SNAPSHOT = "FULL_SNAPSHOT"
    SNAPSHOT_THEN_INCREMENTAL = "SNAPSHOT_THEN_INCREMENTAL"
    EVENT_STREAM = "EVENT_STREAM"


class FeedEventKind(str, Enum):
    SNAPSHOT = "SNAPSHOT"
    INCREMENTAL = "INCREMENTAL"
    EVENT = "EVENT"
    HEARTBEAT = "HEARTBEAT"
    RECONNECT = "RECONNECT"
    GAP = "GAP"


@dataclass(frozen=True, slots=True)
class FeedQualityConfig:
    max_age_ms: float = 1_500.0
    max_future_skew_ms: float = 1_000.0
    heartbeat_max_age_ms: float = 3_000.0
    max_gap_ms: float = 5_000.0
    max_jitter_ms: float = 1_000.0
    max_latency_ms: float = 1_500.0
    max_spread_bps: float = 1_000.0
    max_mid_jump_fraction: float = 0.15
    min_coherent_events: int = 2
    min_score: float = 80.0
    sample_window: int = 512
    seen_event_window: int = 10_000

    def __post_init__(self) -> None:
        if self.min_coherent_events < 1:
            raise ValueError("min_coherent_events must be >= 1")
        if not 0.0 <= self.min_score <= 100.0:
            raise ValueError("min_score must be between 0 and 100")
        if self.sample_window < 2 or self.seen_event_window < 2:
            raise ValueError("quality windows must be >= 2")


@dataclass(frozen=True, slots=True)
class FeedQualitySnapshot:
    source_id: str
    channel: str
    instrument: str
    mode: str
    ready: bool
    synchronized: bool
    feed_quality_score: float
    reasons: tuple[str, ...]
    generated_at_ms: int
    last_exchange_ts_ms: int | None
    last_received_ts_ms: int | None
    last_heartbeat_ts_ms: int | None
    latest_age_ms: float | None
    heartbeat_age_ms: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    jitter_p95_ms: float | None
    jitter_ema_ms: float | None
    gap_duration_ms: float
    gap_p50_ms: float | None
    gap_p95_ms: float | None
    gap_max_ms: float | None
    stale_rate: float | None
    duplicate_rate: float | None
    out_of_order_rate: float | None
    reconnect_rate: float | None
    coherent_events: int
    total_events: int
    events_unique: int
    accepted_events: int
    safe_ratio: float | None
    depth_levels_bid: int
    depth_levels_ask: int
    depth_usd_5bps: float
    depth_usd_10bps: float
    depth_usd_25bps: float
    snapshots: int
    incrementals: int
    duplicates: int
    stale_events: int
    gaps: int
    non_monotonic: int
    invalid_bbo: int
    crossed_books: int
    outliers: int
    reconnects: int
    snapshot_conflicts: int
    unresolved_gap: bool
    reason_counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        result["reason_counts"] = dict(self.reason_counts)
        return result




class FeedQualityGate:
    """Reconstruct feed state and expose a measurable readiness decision."""

    def __init__(
        self,
        *,
        source_id: str,
        channel: str,
        instrument: str,
        mode: FeedMode,
        config: FeedQualityConfig | None = None,
    ) -> None:
        self.source_id = str(source_id)
        self.channel = str(channel)
        self.instrument = str(instrument)
        self.mode = FeedMode(mode)
        self.config = config or FeedQualityConfig()

        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._snapshot_seen = False
        self._incremental_seen = False
        self._synchronized = False
        self._unresolved_gap = self.mode is FeedMode.SNAPSHOT_THEN_INCREMENTAL
        self._coherent_events = 0
        self._last_mid: float | None = None
        self._last_exchange_ts_ms: int | None = None
        self._last_received_ts_ms: int | None = None
        self._last_heartbeat_ts_ms: int | None = None
        self._last_sequence: int | None = None
        self._connection_id: str | None = None
        self._last_recovery_frame_ts_ms: int | None = None

        self._latencies: deque[float] = deque(maxlen=self.config.sample_window)
        self._intervals: deque[float] = deque(maxlen=self.config.sample_window)
        self._jitters: deque[float] = deque(maxlen=self.config.sample_window)
        self._gap_durations: deque[float] = deque(maxlen=self.config.sample_window)
        self._jitter_ema: float | None = None
        self._last_latency_ms: float | None = None
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._reason_counts: Counter[str] = Counter()
        self._last_reasons: tuple[str, ...] = ()

        self.total_events = 0
        self.accepted_events = 0
        self.snapshots = 0
        self.incrementals = 0
        self.duplicates = 0
        self.stale_events = 0
        self.gaps = 0
        self.non_monotonic = 0
        self.invalid_bbo = 0
        self.crossed_books = 0
        self.outliers = 0
        self.reconnects = 0
        self.snapshot_conflicts = 0

    @property
    def bids(self) -> dict[float, float]:
        return dict(self._bids)

    @property
    def asks(self) -> dict[float, float]:
        return dict(self._asks)

    def mark_heartbeat(self, *, received_ts_ms: int) -> None:
        self._last_heartbeat_ts_ms = int(received_ts_ms)

    def mark_reconnect(self, *, received_ts_ms: int, connection_id: str | None = None) -> None:
        self.reconnects += 1
        self._connection_id = connection_id
        self._snapshot_seen = False
        self._incremental_seen = False
        self._synchronized = False
        self._unresolved_gap = True
        self._coherent_events = 0
        self._bids.clear()
        self._asks.clear()
        self._last_mid = None
        self._last_sequence = None
        self._last_recovery_frame_ts_ms = None
        self._last_received_ts_ms = int(received_ts_ms)
        self._record_reason("RECONNECT_REQUIRES_RESYNCHRONIZATION")

    def mark_gap(self, *, reason: str = "EXPLICIT_GAP") -> None:
        self.gaps += 1
        self._unresolved_gap = True
        self._synchronized = False
        self._coherent_events = 0
        self._last_recovery_frame_ts_ms = None
        self._record_reason(reason)

    def ingest_book_snapshot(
        self,
        *,
        bids: Iterable[Any],
        asks: Iterable[Any],
        exchange_ts_ms: int,
        received_ts_ms: int,
        event_id: str | None = None,
        sequence: int | None = None,
    ) -> FeedQualitySnapshot:
        reasons = self._start_observation(
            exchange_ts_ms=exchange_ts_ms,
            received_ts_ms=received_ts_ms,
            event_id=event_id,
            sequence=sequence,
        )
        self.snapshots += 1
        try:
            next_bids = _normalise_levels(bids)
            next_asks = _normalise_levels(asks)
        except (TypeError, ValueError):
            reasons.append("INVALID_BOOK_LEVEL")
            self.invalid_bbo += 1
            return self._reject(reasons, received_ts_ms)

        book_reasons, mid = self._validate_book(next_bids, next_asks)
        reasons.extend(book_reasons)
        if self._contains_hard_rejection(reasons):
            return self._reject(reasons, received_ts_ms)

        had_gap = self._unresolved_gap or "TEMPORAL_GAP" in reasons or "SEQUENCE_GAP" in reasons
        self._bids, self._asks = next_bids, next_asks
        self._snapshot_seen = True
        self._unresolved_gap = False
