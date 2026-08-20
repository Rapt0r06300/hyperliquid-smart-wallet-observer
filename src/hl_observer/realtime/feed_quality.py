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

import hashlib
import json
import math
import statistics
from collections import Counter, deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.realtime.event_identity import canonicalize_frame


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
    stale_rate: float | None
    duplicate_rate: float | None
    out_of_order_rate: float | None
    reconnect_rate: float | None
    coherent_events: int
    total_events: int
    accepted_events: int
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


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stable_event_id(payload: Any) -> str:
    """Return a deterministic hash for deduplication and provenance."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_levels(levels: Iterable[Any]) -> dict[float, float]:
    result: dict[float, float] = {}
    for level in levels:
        if isinstance(level, Mapping):
            price_raw = level.get("px", level.get("price"))
            size_raw = level.get("sz", level.get("size"))
        elif isinstance(level, Sequence) and not isinstance(level, (str, bytes)) and len(level) >= 2:
            price_raw, size_raw = level[0], level[1]
        else:
            raise ValueError("invalid book level")
        price = float(price_raw)
        size = float(size_raw)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("invalid book price")
        if not math.isfinite(size) or size < 0:
            raise ValueError("invalid book size")
        if size > 0:
            result[price] = size
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
        self._last_mid = mid
        self.accepted_events += 1
        self._coherent_events = 1 if had_gap else self._coherent_events + 1
        self._synchronized = self._coherent_events >= self.config.min_coherent_events
        self._last_reasons = tuple(dict.fromkeys(reasons))
        return self.snapshot(now_ms=received_ts_ms)

    def ingest_book_incremental(
        self,
        *,
        bid_updates: Iterable[Any] = (),
        ask_updates: Iterable[Any] = (),
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
        self.incrementals += 1
        if self.mode is FeedMode.FULL_SNAPSHOT:
            reasons.append("INCREMENTAL_UNSUPPORTED_FOR_FULL_SNAPSHOT_FEED")
        if not self._snapshot_seen:
            reasons.append("INCREMENTAL_BEFORE_SNAPSHOT")
        if self._contains_hard_rejection(reasons):
            return self._reject(reasons, received_ts_ms)

        next_bids = dict(self._bids)
        next_asks = dict(self._asks)
        try:
            self._apply_updates(next_bids, bid_updates)
            self._apply_updates(next_asks, ask_updates)
        except (TypeError, ValueError):
            reasons.append("INVALID_BOOK_LEVEL")
            self.invalid_bbo += 1
            return self._reject(reasons, received_ts_ms)

        book_reasons, mid = self._validate_book(next_bids, next_asks)
        reasons.extend(book_reasons)
        if self._contains_hard_rejection(reasons):
            return self._reject(reasons, received_ts_ms)

        self._bids, self._asks = next_bids, next_asks
        self._incremental_seen = True
        self._last_mid = mid
        self.accepted_events += 1
        self._coherent_events += 1
        self._synchronized = (
            self._snapshot_seen
            and self._incremental_seen
            and not self._unresolved_gap
            and self._coherent_events >= self.config.min_coherent_events
        )
        self._last_reasons = tuple(dict.fromkeys(reasons))
        return self.snapshot(now_ms=received_ts_ms)

    def ingest_event(
        self,
        *,
        payload: Any,
        exchange_ts_ms: int,
        received_ts_ms: int,
        event_id: str | None = None,
        sequence: int | None = None,
        is_snapshot: bool = False,
    ) -> FeedQualitySnapshot:
        if self.mode is FeedMode.FULL_SNAPSHOT:
            raise ValueError("use ingest_book_snapshot for FULL_SNAPSHOT feeds")
        reasons = self._start_observation(
            exchange_ts_ms=exchange_ts_ms,
            received_ts_ms=received_ts_ms,
            event_id=event_id or stable_event_id(payload),
            sequence=sequence,
        )
        if is_snapshot:
            self.snapshots += 1
            self._snapshot_seen = True
            self._incremental_seen = False
            self._unresolved_gap = False
            self._coherent_events = 0
        else:
            self.incrementals += 1
            if self.mode is FeedMode.SNAPSHOT_THEN_INCREMENTAL and not self._snapshot_seen:
                reasons.append("INCREMENTAL_BEFORE_SNAPSHOT")
            else:
                self._incremental_seen = True

        if self._contains_hard_rejection(reasons):
            return self._reject(reasons, received_ts_ms)

        self.accepted_events += 1
        if self.mode is FeedMode.EVENT_STREAM:
            self._advance_event_stream_recovery(
                reasons=reasons,
                received_ts_ms=received_ts_ms,
            )
        else:
            self._coherent_events += 1
            self._synchronized = (
                self._snapshot_seen
                and self._incremental_seen
                and not self._unresolved_gap
                and self._coherent_events >= self.config.min_coherent_events
            )
        self._last_reasons = tuple(dict.fromkeys(reasons))
        return self.snapshot(now_ms=received_ts_ms)

    def ingest_event_batch(
        self,
        *,
        payloads: Iterable[Mapping[str, Any]],
        received_ts_ms: int,
        frame_sequence: int | None = None,
        is_snapshot: bool = False,
    ) -> list[FeedQualitySnapshot]:
        """Ingest all items from one transport frame without false sequence gaps.

        A frame sequence is applied once, to the first item only.  Snapshot
        batches establish a baseline but do not pretend that the remaining
        items in that same frame are post-snapshot incrementals.
        """

        events = canonicalize_frame(
            payloads,
            source=self.source_id,
            channel=self.channel,
            received_at_ms=received_ts_ms,
            frame_sequence=frame_sequence,
        )
        snapshots: list[FeedQualitySnapshot] = []
        accepted_in_frame = False
        frame_reasons: list[str] = []
        if is_snapshot:
            self.snapshots += 1
            self._snapshot_seen = True
            self._incremental_seen = False
            self._unresolved_gap = False
            self._coherent_events = 0
        for index, event in enumerate(events):
            exchange_ts = (
                event.exchange_ts_ms
                if event.exchange_ts_ms is not None
                else int(received_ts_ms)
            )
            reasons = self._start_observation(
                exchange_ts_ms=exchange_ts,
                received_ts_ms=received_ts_ms,
                event_id=event.stable_event_id,
                sequence=frame_sequence if index == 0 else None,
            )
            if self._contains_hard_rejection(reasons):
                snapshots.append(self._reject(reasons, received_ts_ms))
                continue
            self.accepted_events += 1
            accepted_in_frame = True
            frame_reasons.extend(reasons)
            if self.mode is not FeedMode.EVENT_STREAM:
                self._coherent_events += 1
            self._last_reasons = tuple(dict.fromkeys(reasons))
            snapshots.append(self.snapshot(now_ms=received_ts_ms))
        if not is_snapshot and events:
            self.incrementals += 1
            self._incremental_seen = True
        if self.mode is FeedMode.EVENT_STREAM:
            if accepted_in_frame:
                self._advance_event_stream_recovery(
                    reasons=frame_reasons,
                    received_ts_ms=received_ts_ms,
                )
                self._last_reasons = tuple(dict.fromkeys(frame_reasons))
        else:
            self._synchronized = (
                self._snapshot_seen
                and self._incremental_seen
                and not self._unresolved_gap
                and self._coherent_events >= self.config.min_coherent_events
            )
        if snapshots:
            snapshots[-1] = self.snapshot(now_ms=received_ts_ms)
        return snapshots

    def snapshot(self, *, now_ms: int) -> FeedQualitySnapshot:
        now = int(now_ms)
        latest_age = (
            None if self._last_received_ts_ms is None else max(0.0, now - self._last_received_ts_ms)
        )
        heartbeat_age = (
            None
            if self._last_heartbeat_ts_ms is None
            else max(0.0, now - self._last_heartbeat_ts_ms)
        )
        readiness_reasons: list[str] = []
        if not self._synchronized:
            readiness_reasons.append("FEED_NOT_SYNCHRONIZED")
        if self._unresolved_gap:
            readiness_reasons.append("UNRESOLVED_GAP")
        if latest_age is None or latest_age > self.config.max_age_ms:
            readiness_reasons.append("LATEST_EVENT_STALE")
        if heartbeat_age is None or heartbeat_age > self.config.heartbeat_max_age_ms:
            readiness_reasons.append("HEARTBEAT_STALE")
        if self.mode is not FeedMode.EVENT_STREAM and (not self._bids or not self._asks):
            readiness_reasons.append("BBO_UNAVAILABLE")

        score = self._score()
        if score < self.config.min_score:
            readiness_reasons.append("FEED_QUALITY_SCORE_TOO_LOW")
        reasons = tuple(dict.fromkeys((*self._last_reasons, *readiness_reasons)))
        ready = not readiness_reasons
        denominator = self.total_events
        ratio = (
            (lambda numerator: numerator / denominator)
            if denominator
            else (lambda _numerator: None)
        )
        return FeedQualitySnapshot(
            source_id=self.source_id,
            channel=self.channel,
            instrument=self.instrument,
            mode=self.mode.value,
            ready=ready,
            synchronized=self._synchronized,
            feed_quality_score=score,
            reasons=reasons,
            generated_at_ms=now,
            last_exchange_ts_ms=self._last_exchange_ts_ms,
            last_received_ts_ms=self._last_received_ts_ms,
            last_heartbeat_ts_ms=self._last_heartbeat_ts_ms,
            latest_age_ms=latest_age,
            heartbeat_age_ms=heartbeat_age,
            latency_p50_ms=_percentile(tuple(self._latencies), 0.50),
            latency_p95_ms=_percentile(tuple(self._latencies), 0.95),
            latency_p99_ms=_percentile(tuple(self._latencies), 0.99),
            jitter_p95_ms=_percentile(tuple(self._jitters), 0.95),
            jitter_ema_ms=self._jitter_ema,
            gap_duration_ms=round(sum(self._gap_durations), 3),
            stale_rate=ratio(self.stale_events),
            duplicate_rate=ratio(self.duplicates),
            out_of_order_rate=ratio(self.non_monotonic),
            reconnect_rate=ratio(self.reconnects),
            coherent_events=self._coherent_events,
            total_events=self.total_events,
            accepted_events=self.accepted_events,
            snapshots=self.snapshots,
            incrementals=self.incrementals,
            duplicates=self.duplicates,
            stale_events=self.stale_events,
            gaps=self.gaps,
            non_monotonic=self.non_monotonic,
            invalid_bbo=self.invalid_bbo,
            crossed_books=self.crossed_books,
            outliers=self.outliers,
            reconnects=self.reconnects,
            snapshot_conflicts=self.snapshot_conflicts,
            unresolved_gap=self._unresolved_gap,
            reason_counts=dict(self._reason_counts),
        )

    def _start_observation(
        self,
        *,
        exchange_ts_ms: int,
        received_ts_ms: int,
        event_id: str | None,
        sequence: int | None,
    ) -> list[str]:
        self.total_events += 1
        exchange_ts = int(exchange_ts_ms)
        received_ts = int(received_ts_ms)
        reasons: list[str] = []

        if event_id and not self._remember_event(event_id):
            self.duplicates += 1
            reasons.append("DUPLICATE_EVENT")

        if self._last_exchange_ts_ms is not None and exchange_ts < self._last_exchange_ts_ms:
            self.non_monotonic += 1
            reasons.append("NON_MONOTONIC_EXCHANGE_TIMESTAMP")

        latency = received_ts - exchange_ts
        if latency < -self.config.max_future_skew_ms:
            self.outliers += 1
            reasons.append("EXCHANGE_TIMESTAMP_IN_FUTURE")
        else:
            bounded_latency = max(0.0, float(latency))
            self._latencies.append(bounded_latency)
            if self._last_latency_ms is not None:
                jitter = abs(bounded_latency - self._last_latency_ms)
                self._jitters.append(jitter)
                self._jitter_ema = (
                    jitter
                    if self._jitter_ema is None
                    else 0.2 * jitter + 0.8 * self._jitter_ema
                )
            self._last_latency_ms = bounded_latency
        if latency > self.config.max_age_ms:
            self.stale_events += 1
            reasons.append("STALE_EVENT")

        if self._last_received_ts_ms is not None:
            interval = float(received_ts - self._last_received_ts_ms)
            if interval < 0:
                self.non_monotonic += 1
                reasons.append("NON_MONOTONIC_RECEIVE_TIMESTAMP")
            else:
                self._intervals.append(interval)
                # Independent event streams (public trades, fills) are sparse by
                # nature: silence for one instrument is not proof that the
                # transport dropped data.  Their real transport gaps are marked
                # explicitly by the websocket supervisor/collector.  Snapshot
                # and incremental state feeds still require cadence continuity.
                if (
                    interval > self.config.max_gap_ms
                    and self.mode is not FeedMode.EVENT_STREAM
                ):
                    self.gaps += 1
                    self._gap_durations.append(interval)
                    self._unresolved_gap = True
                    self._synchronized = False
                    self._coherent_events = 0
                    reasons.append("TEMPORAL_GAP")

        if sequence is not None:
            seq = int(sequence)
            if self._last_sequence is not None:
                if seq <= self._last_sequence:
                    self.non_monotonic += 1
                    reasons.append("NON_MONOTONIC_SEQUENCE")
                elif seq > self._last_sequence + 1:
                    self.gaps += 1
                    self._unresolved_gap = True
                    self._synchronized = False
                    self._coherent_events = 0
                    reasons.append("SEQUENCE_GAP")
            self._last_sequence = seq

        self._last_exchange_ts_ms = max(exchange_ts, self._last_exchange_ts_ms or exchange_ts)
        self._last_received_ts_ms = received_ts
        for reason in reasons:
            self._record_reason(reason)
        return reasons

    def _advance_event_stream_recovery(
        self,
        *,
        reasons: list[str],
        received_ts_ms: int,
    ) -> None:
        """Recover an independent event stream after coherent future frames.

        A trade stream has no baseline snapshot to request after a reconnect.
        Each future trade is independently meaningful, so the safe recovery
        contract is a bounded warm-up over distinct transport frames.  The
        historical gap remains counted; only future consumption is re-enabled.
        """

        if any(reason in {"TEMPORAL_GAP", "SEQUENCE_GAP"} for reason in reasons):
            self._coherent_events = 0
            self._last_recovery_frame_ts_ms = None
            self._synchronized = False
            return

        frame_ts = int(received_ts_ms)
        if self._last_recovery_frame_ts_ms != frame_ts:
            self._coherent_events += 1
            self._last_recovery_frame_ts_ms = frame_ts

        if (
            self._unresolved_gap
            and self._coherent_events >= self.config.min_coherent_events
        ):
            self._unresolved_gap = False
            reasons.append("EVENT_STREAM_RECOVERED")
            self._record_reason("EVENT_STREAM_RECOVERED")

        self._synchronized = (
            not self._unresolved_gap
            and self._coherent_events >= self.config.min_coherent_events
        )

    def _validate_book(
        self,
        bids: Mapping[float, float],
        asks: Mapping[float, float],
    ) -> tuple[list[str], float | None]:
        reasons: list[str] = []
        if not bids or not asks:
            self.invalid_bbo += 1
            reasons.append("EMPTY_BOOK_SIDE")
            return reasons, None
        best_bid = max(bids)
        best_ask = min(asks)
        if best_ask <= best_bid:
            self.crossed_books += 1
            reasons.append("CROSSED_OR_LOCKED_BOOK")
            return reasons, None
        mid = (best_bid + best_ask) / 2.0
        spread_bps = 10_000.0 * (best_ask - best_bid) / mid
        if spread_bps > self.config.max_spread_bps:
            self.invalid_bbo += 1
            reasons.append("SPREAD_OUTLIER")
        if self._last_mid is not None:
            jump = abs(mid - self._last_mid) / self._last_mid
            if jump > self.config.max_mid_jump_fraction:
                self.outliers += 1
                reasons.append("MID_PRICE_OUTLIER")
        for reason in reasons:
            self._record_reason(reason)
        return reasons, mid

    @staticmethod
    def _apply_updates(book: dict[float, float], updates: Iterable[Any]) -> None:
        for level in updates:
            if isinstance(level, Mapping):
                price_raw = level.get("px", level.get("price"))
                size_raw = level.get("sz", level.get("size"))
            elif isinstance(level, Sequence) and not isinstance(level, (str, bytes)) and len(level) >= 2:
                price_raw, size_raw = level[0], level[1]
            else:
                raise ValueError("invalid book update")
            price, size = float(price_raw), float(size_raw)
            if not math.isfinite(price) or price <= 0 or not math.isfinite(size) or size < 0:
                raise ValueError("invalid book update")
            if size == 0:
                book.pop(price, None)
            else:
                book[price] = size

    def _remember_event(self, event_id: str) -> bool:
        key = str(event_id)
        if key in self._seen_ids:
            return False
        self._seen_ids.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self.config.seen_event_window:
            self._seen_ids.discard(self._seen_order.popleft())
        return True

    @staticmethod
    def _contains_hard_rejection(reasons: Sequence[str]) -> bool:
        hard = {
            "DUPLICATE_EVENT",
            "NON_MONOTONIC_EXCHANGE_TIMESTAMP",
            "NON_MONOTONIC_RECEIVE_TIMESTAMP",
            "NON_MONOTONIC_SEQUENCE",
            "EXCHANGE_TIMESTAMP_IN_FUTURE",
            "STALE_EVENT",
            "INVALID_BOOK_LEVEL",
            "EMPTY_BOOK_SIDE",
            "CROSSED_OR_LOCKED_BOOK",
            "SPREAD_OUTLIER",
            "MID_PRICE_OUTLIER",
            "INCREMENTAL_BEFORE_SNAPSHOT",
            "INCREMENTAL_UNSUPPORTED_FOR_FULL_SNAPSHOT_FEED",
        }
        return any(reason in hard for reason in reasons)

    def _reject(self, reasons: Sequence[str], now_ms: int) -> FeedQualitySnapshot:
        unique = tuple(dict.fromkeys(reasons))
        self._last_reasons = unique
        for reason in unique:
            self._record_reason(reason)
        return self.snapshot(now_ms=int(now_ms))

    def _record_reason(self, reason: str) -> None:
        self._reason_counts[str(reason)] += 1

    def _score(self) -> float:
        denominator = max(1, self.total_events)
        score = 100.0
        score -= 30.0 * self.stale_events / denominator
        score -= 12.0 * self.duplicates / denominator
        score -= 22.0 * self.gaps / denominator
        score -= 22.0 * self.non_monotonic / denominator
        score -= 20.0 * (self.invalid_bbo + self.crossed_books) / denominator
        score -= 18.0 * self.outliers / denominator

        latency_p95 = _percentile(tuple(self._latencies), 0.95)
        if latency_p95 is not None and self.config.max_latency_ms > 0:
            score -= min(12.0, 12.0 * latency_p95 / self.config.max_latency_ms)
        jitter_p95 = _percentile(tuple(self._jitters), 0.95)
        if jitter_p95 is not None and self.config.max_jitter_ms > 0:
            score -= min(10.0, 10.0 * jitter_p95 / self.config.max_jitter_ms)
        score -= min(8.0, self.reconnects * 0.5)
        if not self._synchronized:
            score -= 25.0
        if self._unresolved_gap:
            score -= 15.0
        return round(max(0.0, min(100.0, score)), 3)


__all__ = [
    "FeedEventKind",
    "FeedMode",
    "FeedQualityConfig",
    "FeedQualityGate",
    "FeedQualitySnapshot",
    "stable_event_id",
]
