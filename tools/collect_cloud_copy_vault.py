#!/usr/bin/env python3
"""Bounded GitHub-hosted Copy-Vault collection window.

Fresh-data rule:
- discover the public observation universe at t0;
- select deterministic observation-only vaults from that t0 snapshot;
- collect userFills forward from t0 over public WebSocket subscriptions;
- reconcile ONLY [t0, t1] with public userFillsByTime after the window;
- never use pre-selection history as forward evidence.

No key, signature, order, deposit, withdrawal or private endpoint is used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import collecter_vaults as CV  # noqa: E402

from hl_observer.collection.partitioned_tick_dataset import (  # noqa: E402
    PartitionedTickDatasetWriter,
)
from hl_observer.collection.tick_dataset import TickEnvelope  # noqa: E402
from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402
from hl_observer.collection.vault_fills_backfill import (  # noqa: E402
    CAP_USERFILLS,
    canonical_fill_id,
    dedupliquer,
    parser_fills,
)
from hl_observer.datasets.v2_export import (  # noqa: E402
    build_manifest_from_tick_shard,
    write_manifest,
)
from hl_observer.datasets.v2_pipeline import (  # noqa: E402
    V2_REPOSITORY,
    V2_SCHEMA,
    admission_rejection,
    finalize_manifest,
    infer_reconciliation_status,
    locally_replay_admissible,
    summarize_admission_rejections,
)
from hl_observer.normalization.instrument_identity import (  # noqa: E402
    preserve_native_instrument_symbol as canonical_copy_vault_coin,
)
from hl_observer.normalization.l2_book import validate_l2_book_sides  # noqa: E402
from hl_observer.realtime.feed_quality import FeedEventKind  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_SUBSCRIPTIONS_PER_SOCKET = 5
MAX_UNIQUE_USERS_PER_IP = 10
MAX_RECONCILIATION_REQUESTS_PER_VAULT = 512
RECONCILIATION_PER_VAULT_TIMEOUT_S = 90.0
# Hyperliquid shares the 1200 weight/minute REST limit across /info calls.
# Keep this collector's coordinated budget at 1080 to leave recovery headroom.
REST_WEIGHT_BUDGET_PER_MINUTE = 1_080
BROAD_SWEEP_REQUEST_INTERVAL_S = 0.14
BROAD_SWEEP_CONCURRENCY = 8
MAX_PRIORITY_WS_VAULTS = 10
MAX_WS_SUBSCRIPTIONS_PER_IP = 1_000
COPY_VAULT_MARKET_CHANNEL_TYPES = ("bbo", "l2Book", "trades", "activeAssetCtx")
# Reserve three user-specific feeds for each priority vault plus ten spare slots.
MAX_COPY_VAULT_MARKET_INSTRUMENTS = (
    MAX_WS_SUBSCRIPTIONS_PER_IP - (MAX_PRIORITY_WS_VAULTS * 3) - 10
) // len(COPY_VAULT_MARKET_CHANNEL_TYPES)
PRIORITY_AUDIT_ROTATION_SLOTS = 2
DEFAULT_HISTORY_LOOKBACK_HOURS = 72.0
MAX_HISTORY_LOOKBACK_HOURS = 72.0
MAX_PUBLIC_USERFILLS = 10_000
MAX_USERFILLS_RESPONSE_WEIGHT = 20 + CAP_USERFILLS // 20
MAX_TIME_RANGE_RESPONSE_ROWS = 500
MAX_TIME_RANGE_REQUESTS = 64
MAX_TIME_RANGE_RESPONSE_WEIGHT = 20 + MAX_TIME_RANGE_RESPONSE_ROWS // 20
MAX_ACCOUNTING_BACKFILL_REQUESTS_PER_CHANNEL = 8
MAX_L2_DIAGNOSTIC_RECORDS = 256
SUBSCRIPTION_ACK_TIMEOUT_S = 10.0
SUBSCRIPTION_TIMEOUT_POLL_S = 0.1


class RestWeightPacer:
    """Coordinate this collector's public /info requests under one weight budget."""

    def __init__(
        self,
        *,
        budget_weight_per_minute: int = REST_WEIGHT_BUDGET_PER_MINUTE,
        monotonic_fn: Any = time.monotonic,
        sleep_fn: Any = asyncio.sleep,
    ) -> None:
        budget = int(budget_weight_per_minute)
        if not 1 <= budget <= 1_200:
            raise ValueError("REST weight budget must be in 1..1200 per minute")
        self.budget_weight_per_minute = budget
        self._monotonic = monotonic_fn
        self._sleep = sleep_fn
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire_weight(self, weight: int) -> None:
        requested = max(1, int(weight))
        async with self._lock:
            now = float(self._monotonic())
            delay = max(0.0, self._next_at - now)
            if delay > 0:
                await self._sleep(delay)
            now = float(self._monotonic())
            self._next_at = max(now, self._next_at) + (
                60.0 * requested / self.budget_weight_per_minute
            )

    async def before_request(self, *, weight: int | None = None) -> None:
        # Reserve the maximum possible weight before sending to stay safe when
        # several large responses arrive concurrently (20 + 2000 / 20).
        await self.acquire_weight(
            MAX_USERFILLS_RESPONSE_WEIGHT if weight is None else int(weight)
        )


class AsyncTickSink:
    def __init__(
        self,
        writer: PartitionedTickDatasetWriter,
        *,
        max_queue: int = 100_000,
        batch_size: int = 2_000,
    ) -> None:
        self.writer = writer
        self.queue: asyncio.Queue[TickEnvelope] = asyncio.Queue(maxsize=max_queue)
        self.batch_size = max(1, int(batch_size))
        self.accepted = 0
        self.persisted = 0
        self.backpressure_events = 0
        self.drops: dict[tuple[str, str, str], int] = defaultdict(int)
        self._stop = False

    @staticmethod
    def key(envelope: TickEnvelope) -> tuple[str, str, str]:
        return (
            str(envelope.source_id),
            str(envelope.channel),
            str(envelope.instrument),
        )

    def emit(self, envelope: TickEnvelope) -> None:
        # Legacy callback: congestion remains explicit, never silently ignored.
        try:
            self.queue.put_nowait(envelope)
            self.accepted += 1
        except asyncio.QueueFull:
            self.drops[self.key(envelope)] += 1

    async def emit_async(self, envelope: TickEnvelope) -> None:
        # Async capture should wait for a durable writer slot instead of
        # silently losing a causally significant fill/position observation.
        if self.queue.full():
            self.backpressure_events += 1
        await self.queue.put(envelope)
        self.accepted += 1

    async def run(self) -> None:
        while not self._stop or not self.queue.empty():
            try:
                first = await asyncio.wait_for(self.queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            batch = [first]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            records = await asyncio.to_thread(self.writer.append_batch_records, batch)
            self.persisted += len(records)
            for _ in batch:
                self.queue.task_done()

    async def close(self) -> None:
        self._stop = True
        await self.queue.join()


async def _emit_with_backpressure(sink: Any, envelope: TickEnvelope) -> None:
    async_emit = getattr(sink, "emit_async", None)
    if callable(async_emit):
        await async_emit(envelope)
    else:
        sink.emit(envelope)


def discover_vaults(
    *,
    max_vaults: int,
    min_tvl_usd: float = CV.MIN_TVL_PUBLIC_USD,
    min_age_days: float = CV.MIN_AGE_PUBLIC_DAYS,
    now_ms: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and freeze one public observation universe at selection time."""
    selected_at_ms = int(time.time() * 1_000) if now_ms is None else int(now_ms)
    raw = CV._get_vaults_public()
    rows = CV.parser_univers_public(
        raw,
        now_ms=selected_at_ms,
        min_tvl_usd=min_tvl_usd,
        min_age_days=min_age_days,
        max_vaults=max(1, int(max_vaults)),
    )
    if not rows:
        raise RuntimeError("public Copy-Vault observation universe is empty")
    selection = {
        "schema": "alina.copy_vault_selection.v1",
        "selected_at_ms": selected_at_ms,
        "source": CV.URL_VAULTS,
        "filters": {
            "min_tvl_usd": float(min_tvl_usd),
            "min_age_days": float(min_age_days),
            "max_vaults": int(max_vaults),
            "relationship": "normal",
            "is_closed": False,
        },
        "vault_count": len(rows),
        "vaults": rows,
        "observation_only": True,
        "read_only": True,
        "real_execution": False,
    }
    return rows, selection


def selection_envelope(row: Mapping[str, Any], selection: Mapping[str, Any]) -> TickEnvelope:
    vault = str(row["address"]).lower()
    selected_at_ms = int(selection["selected_at_ms"])
    return TickEnvelope(
        source_id="hyperliquid_public_vaults",
        channel="copy_vault_selection",
        instrument=vault,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={
            "selection": dict(row),
            "filters": dict(selection["filters"]),
        },
        exchange_ts_ms=None,
        received_ts_ms=selected_at_ms,
        local_monotonic_ns=time.monotonic_ns(),
        connection_id=None,
        sequence=None,
        provenance={
            "url": str(selection["source"]),
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "selection_causal": True,
            "timestamp_semantics": "receive_observation_time_only",
        },
        parsed_summary={
            "tvl_usd": row.get("tvl_usd"),
            "age_days": row.get("age_j"),
            "apr_pct_display_only": row.get("apr_pct"),
            "observation_only": True,
            "selected_at_ms": selected_at_ms,
            "data_gate_ready": False,
        },
    )


def userfills_envelope(
    message: Mapping[str, Any],
    *,
    vault: str,
    receive_wall_ms: int,
    receive_mono_ns: int,
    connection_id: str,
) -> tuple[TickEnvelope | None, list[dict[str, Any]]]:
    data = message.get("data")
    snapshot_value = data.get("isSnapshot") if isinstance(data, Mapping) else None
    snapshot_flag_valid = type(snapshot_value) is bool
    fills = parser_message_userfills(
        message,
        vault=vault,
        received_at_ms=receive_wall_ms,
        receive_mono_ns=receive_mono_ns,
        connection_id=connection_id,
    )
    if not fills and not (snapshot_flag_valid and snapshot_value is True):
        return None, []
    is_snapshot = snapshot_value if snapshot_flag_valid else None
    for fill in fills:
        fill["isSnapshot"] = is_snapshot
    exchange_times = [
        int(fill["ts_ms"])
        for fill in fills
        if fill.get("ts_ms") is not None
    ]
    exchange_ts_ms = max(exchange_times) if exchange_times else None
    sequence = None
    for candidate in (
        message.get("sequence"),
        message.get("seq"),
        data.get("sequence") if isinstance(data, Mapping) else None,
        data.get("seq") if isinstance(data, Mapping) else None,
    ):
        try:
            if candidate is not None:
                sequence = int(candidate)
                break
        except (TypeError, ValueError, OverflowError):
            pass

    channel = "copy_vault_snapshot" if is_snapshot is True else "copy_vault_fills"
    event_kind = (
        FeedEventKind.SNAPSHOT
        if is_snapshot is True
        else FeedEventKind.EVENT
        if is_snapshot is False
        else "UNCLASSIFIED"
    )
    return (
        TickEnvelope(
            source_id="hyperliquid_public_userfills",
            channel=channel,
            instrument=vault.lower(),
            event_kind=event_kind,
            raw_payload=dict(message),
            exchange_ts_ms=exchange_ts_ms,
            received_ts_ms=receive_wall_ms,
            local_monotonic_ns=receive_mono_ns,
            connection_id=connection_id,
            sequence=sequence,
            provenance={
                "url": WS_URL,
                "network": "mainnet",
                "access": "read_only",
                "transport": "websocket",
                "authenticated": False,
                "selection_causal": True,
            },
            parsed_summary={
                "event_count": len(fills),
                "is_snapshot": is_snapshot,
                "snapshot_flag_status": "VALID" if snapshot_flag_valid else "MISSING_OR_INVALID",
                "first_fill_ts_ms": min(exchange_times) if exchange_times else None,
                "last_fill_ts_ms": exchange_ts_ms,
                "data_gate_ready": False,
            },
        ),
        fills,
    )


def _valid_l2_levels(levels: Any) -> bool:
    if not isinstance(levels, list) or len(levels) != 2:
        return False
    normalized_sides: list[list[list[float]]] = []
    for side in levels:
        if not isinstance(side, list):
            return False
        normalized_side: list[list[float]] = []
        for level in side:
            if not isinstance(level, Mapping):
                return False
            parsed: dict[str, Decimal] = {}
            for field in ("px", "sz"):
                value = level.get(field)
                if isinstance(value, bool) or value is None:
                    return False
                try:
                    number = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError):
                    return False
                if not number.is_finite() or number <= 0:
                    return False
                parsed[field] = number
            if type(level.get("n")) is not int or level["n"] <= 0:
                return False
            try:
                normalized_side.append([float(parsed["px"]), float(parsed["sz"])])
            except (OverflowError, ValueError):
                return False
        normalized_sides.append(normalized_side)
    if any(not side for side in normalized_sides):
        return False
    bids, asks = normalized_sides
    _, reason = validate_l2_book_sides(
        bids,
        asks,
        bid=bids[0][0],
        ask=asks[0][0],
    )
    return reason is None


def _l2_message_status(message: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if str(message.get("channel") or "") != "l2Book":
        return "wrong_channel", None
    data = message.get("data")
    if not isinstance(data, Mapping):
        return "other_schema", None
    coin = canonical_copy_vault_coin(data.get("coin"))
    if not coin:
        return "missing_coin", None
    timestamp = data.get("time")
    if type(timestamp) is not int or timestamp <= 0:
        return "invalid_timestamp", coin
    if not _valid_l2_levels(data.get("levels")):
        return "invalid_levels", coin
    return None, coin


def classify_l2_payload(
    raw_payload: Any,
) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
    """Parse one L2 socket frame and return a stable reason when inadmissible."""
    try:
        message = json.loads(raw_payload)
    except (TypeError, ValueError):
        return None, "invalid_json", None
    if not isinstance(message, Mapping):
        return None, "other_schema", None
    reason, coin = _l2_message_status(message)
    return message, reason, coin


def new_l2_state() -> dict[str, Any]:
    return {
        "frames": 0,
        "reconnects": 0,
        "heartbeats": 0,
        "heartbeats_received": 0,
        "subscription_ack_mismatches": 0,
        "invalid_subscription_acks": 0,
        "received": 0,
        "candidate_frames": 0,
        "rejected": 0,
        "duplicates": 0,
        "rejected_by_reason": {},
        "ignored_by_reason": {},
        "markets": {},
        "connection_events": [],
        "connection_events_dropped": 0,
        "unknown_market_rejections": [],
        "unknown_market_rejections_dropped": 0,
        "market_subscription_requested": 0,
        "market_acknowledged": 0,
        "market_rejected_before_ack": 0,
        "market_cap_omitted_coins": 0,
        "market_accepted_by_channel": {},
        "market_rejected_by_reason": {},
        "market_subscription_rejections": {},
    }


def _append_l2_history(
    state: dict[str, Any], key: str, record: Mapping[str, Any]
) -> None:
    records = state.setdefault(key, [])
    if not isinstance(records, list):
        return
    records.append(dict(record))
    overflow = max(0, len(records) - MAX_L2_DIAGNOSTIC_RECORDS)
    if overflow:
        del records[:overflow]
        state[f"{key}_dropped"] = int(state.get(f"{key}_dropped", 0)) + overflow


def _l2_market_state(state: dict[str, Any], coin: str) -> dict[str, Any]:
    markets = state.setdefault("markets", {})
    market = markets.setdefault(
        coin,
        {
            "received": 0,
            "candidate_frames": 0,
            "accepted": 0,
            "rejected": 0,
            "duplicates": 0,
            "rejected_by_reason": {},
            "ignored_by_reason": {},
            "l2_gap_epoch": 0,
            "last_receive_ts_ms": None,
            "last_exchange_ts_ms": None,
            "last_connection_id": None,
            "last_snapshot_sha256": None,
            "subscription_status": "UNKNOWN",
            "subscription_attempts": [],
            "subscription_attempts_dropped": 0,
            "open_gap_index": None,
            "gaps": [],
            "gaps_dropped": 0,
        },
    )
    return market


def _subscription_identity(subscription: Any) -> tuple[str, str] | None:
    if not isinstance(subscription, Mapping):
        return None
    kind = str(subscription.get("type") or "").strip()
    if kind in COPY_VAULT_MARKET_CHANNEL_TYPES:
        identity = canonical_copy_vault_coin(subscription.get("coin"))
    elif kind in {
        "userFills", "userFundings", "userNonFundingLedgerUpdates",
    }:
        identity = str(subscription.get("user") or "").strip().lower()
    else:
        return None
    if not kind or not identity:
        return None
    return kind, identity


def classify_subscription_ack(
    message: Any,
) -> tuple[str, tuple[str, str] | None, str | None] | None:
    """Parse only a correlated successful/explicitly rejected subscribe ack."""
    if not isinstance(message, Mapping):
        return None
    if str(message.get("channel") or "") != "subscriptionResponse":
        return None
    data = message.get("data")
    if not isinstance(data, Mapping) or data.get("method") != "subscribe":
        return "INVALID", None, "missing_subscribe_method_or_data"
    identity = _subscription_identity(data.get("subscription"))
    if identity is None:
        return "INVALID", None, "missing_or_unsupported_subscription"
    error = data.get("error")
    if error is None:
        error = message.get("error")
    if error is not None and str(error).strip():
        return "REJECTED", identity, str(error).strip()[:256]
    return "ACKNOWLEDGED", identity, None


def _new_subscription_attempt(
    subscription: Mapping[str, Any],
    *,
    connection_id: str,
    sent_at_ms: int,
    sent_monotonic: float,
) -> dict[str, Any]:
    identity = _subscription_identity(subscription)
    if identity is None:
        raise ValueError("unsupported Copy-Vault subscription")
    return {
        "type": identity[0],
        "identity": identity[1],
        "status": "PENDING",
        "connection_id": connection_id,
        "sent_at_ms": sent_at_ms,
        "acknowledged_at_ms": None,
        "timed_out_at_ms": None,
        "invalidated_at_ms": None,
        "late_ack": False,
        "error": None,
        "_deadline_monotonic": sent_monotonic + SUBSCRIPTION_ACK_TIMEOUT_S,
    }


def _append_bounded_attempt(
    attempts: list[dict[str, Any]],
    attempt: dict[str, Any],
    *,
    dropped_counter: dict[str, int] | None = None,
) -> None:
    attempts.append(attempt)
    overflow = max(0, len(attempts) - MAX_L2_DIAGNOSTIC_RECORDS)
    if overflow:
        del attempts[:overflow]
        if dropped_counter is not None:
            dropped_counter["value"] = dropped_counter.get("value", 0) + overflow


async def _subscription_timeout_watchdog(
    attempts: list[dict[str, Any]],
    stop: asyncio.Event,
    on_timeout: Any | None = None,
) -> None:
    while not stop.is_set():
        now = time.monotonic()
        next_delay = SUBSCRIPTION_TIMEOUT_POLL_S
        for attempt in attempts:
            if attempt.get("status") != "PENDING":
                continue
            deadline = attempt.get("_deadline_monotonic")
            if not isinstance(deadline, (int, float)):
                continue
            remaining = float(deadline) - now
            if remaining <= 0:
                attempt["status"] = "TIMED_OUT"
                attempt["timed_out_at_ms"] = int(time.time() * 1_000)
                if on_timeout is not None:
                    on_timeout(attempt)
            else:
                next_delay = min(next_delay, remaining)
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.01, next_delay))
        except asyncio.TimeoutError:
            continue


def _public_subscription_attempts(
    attempts_by_identity: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(identity): [
            {key: value for key, value in attempt.items() if not key.startswith("_")}
            for attempt in attempts
        ]
        for identity, attempts in sorted(attempts_by_identity.items())
    }


def _invalidate_subscription_attempt(
    attempt: dict[str, Any], *, at_ms: int, reason: str
) -> bool:
    status = attempt.get("status")
    if status not in {"PENDING", "ACTIVE", "TIMED_OUT"}:
        return False
    attempt["status_before_invalidation"] = status
    attempt["status"] = "INVALIDATED"
    attempt["invalidated_at_ms"] = at_ms
    attempt["invalidation_reason"] = reason
    return True


def _open_l2_gap(
    state: dict[str, Any],
    coin: str,
    *,
    reason: str,
    at_ms: int,
    connection_id: str | None,
) -> None:
    market = _l2_market_state(state, coin)
    index = market.get("open_gap_index")
    gaps = market["gaps"]
    if type(index) is int and 0 <= index < len(gaps):
        gap = gaps[index]
        reasons = gap.setdefault("reasons", [])
        if reason not in reasons:
            reasons.append(reason)
        gap["last_detected_at_ms"] = at_ms
        return
    last_receive = market.get("last_receive_ts_ms")
    if len(gaps) >= MAX_L2_DIAGNOSTIC_RECORDS:
        del gaps[0]
        market["gaps_dropped"] = int(market.get("gaps_dropped", 0)) + 1
        if type(index) is int:
            market["open_gap_index"] = max(0, index - 1)
    gap = {
        "start_after_receive_ts_ms": last_receive if type(last_receive) is int else at_ms,
        "detected_at_ms": at_ms,
        "last_detected_at_ms": at_ms,
        "reason": reason,
        "reasons": [reason],
        "connection_id": connection_id,
        "recovery_at_ms": None,
        "recovery_connection_id": None,
        "continuity_proven": False,
    }
    market["l2_gap_epoch"] = int(market.get("l2_gap_epoch", 0)) + 1
    gap["l2_gap_epoch"] = market["l2_gap_epoch"]
    gaps.append(gap)
    market["open_gap_index"] = len(gaps) - 1


def _record_l2_rejection(
    state: dict[str, Any],
    reason: str,
    *,
    coin: str | None,
    at_ms: int,
    connection_id: str,
    affected_coins: set[str] | None = None,
) -> None:
    state["rejected"] = int(state.get("rejected", 0)) + 1
    reasons = state.setdefault("rejected_by_reason", {})
    reasons[reason] = int(reasons.get(reason, 0)) + 1
    if coin:
        market = _l2_market_state(state, coin)
        market["received"] += 1
        market["rejected"] += 1
        market_reasons = market.setdefault("rejected_by_reason", {})
        market_reasons[reason] = int(market_reasons.get(reason, 0)) + 1
        _open_l2_gap(
            state,
            coin,
            reason=reason,
            at_ms=at_ms,
            connection_id=connection_id,
        )
        return
    _append_l2_history(
        state,
        "unknown_market_rejections",
        {"time_ms": at_ms, "connection_id": connection_id, "reason": reason},
    )
    for affected_coin in sorted(affected_coins or set()):
        _open_l2_gap(
            state,
            affected_coin,
            reason=reason,
            at_ms=at_ms,
            connection_id=connection_id,
        )


def _record_l2_ignored(state: dict[str, Any], reason: str) -> None:
    reasons = state.setdefault("ignored_by_reason", {})
    reasons[reason] = int(reasons.get(reason, 0)) + 1


def _snapshot_identity(envelope: TickEnvelope) -> str:
    payload = json.dumps(
        envelope.raw_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _l2_snapshot_duplicate_or_invalid(
    state: dict[str, Any], envelope: TickEnvelope
) -> str | None:
    market = _l2_market_state(state, envelope.instrument)
    last_ts = market.get("last_exchange_ts_ms")
    signature = _snapshot_identity(envelope)
    if type(last_ts) is int:
        if envelope.exchange_ts_ms is None or envelope.exchange_ts_ms < last_ts:
            return "invalid_timestamp"
        if envelope.exchange_ts_ms == last_ts:
            if signature == market.get("last_snapshot_sha256"):
                return "duplicate_snapshot"
            return "timestamp_conflict"
    return None


def _record_l2_accepted(
    state: dict[str, Any],
    envelope: TickEnvelope,
    *,
    receive_wall_ms: int,
) -> None:
    market = _l2_market_state(state, envelope.instrument)
    market["received"] += 1
    market["accepted"] += 1
    gap_index = market.get("open_gap_index")
    gaps = market["gaps"]
    if type(gap_index) is int and 0 <= gap_index < len(gaps):
        gap = gaps[gap_index]
        gap["recovery_at_ms"] = receive_wall_ms
        gap["recovery_connection_id"] = envelope.connection_id
        gap["continuity_proven"] = False
        market["open_gap_index"] = None
    market["last_receive_ts_ms"] = receive_wall_ms
    market["last_exchange_ts_ms"] = envelope.exchange_ts_ms
    market["last_connection_id"] = envelope.connection_id
    market["last_snapshot_sha256"] = _snapshot_identity(envelope)
    state["frames"] = int(state.get("frames", 0)) + 1


def _record_l2_duplicate(state: dict[str, Any], envelope: TickEnvelope) -> None:
    market = _l2_market_state(state, envelope.instrument)
    market["received"] += 1
    market["duplicates"] += 1
    ignored = market.setdefault("ignored_by_reason", {})
    ignored["duplicate_snapshot"] = int(ignored.get("duplicate_snapshot", 0)) + 1
    state["duplicates"] = int(state.get("duplicates", 0)) + 1
    _record_l2_ignored(state, "duplicate_snapshot")


def _record_l2_disconnect(
    state: dict[str, Any],
    *,
    connection_id: str,
    markets: set[str],
    at_ms: int,
    error_class: str,
) -> None:
    state["reconnects"] = int(state.get("reconnects", 0)) + 1
    _append_l2_history(
        state,
        "connection_events",
        {
            "event": "disconnect",
            "time_ms": at_ms,
            "connection_id": connection_id,
            "markets": sorted(markets),
            "error_class": error_class,
        },
    )
    for coin in sorted(markets):
        _open_l2_gap(
            state,
            coin,
            reason="websocket_disconnect",
            at_ms=at_ms,
            connection_id=connection_id,
        )


def _l2_market_summary(state: Mapping[str, Any], end_ms: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    markets = state.get("markets")
    if not isinstance(markets, Mapping):
        return result
    for coin, raw_market in sorted(markets.items()):
        if not isinstance(raw_market, Mapping):
            continue
        last_receive = raw_market.get("last_receive_ts_ms")
        age = end_ms - last_receive if type(last_receive) is int else None
        open_index = raw_market.get("open_gap_index")
        gaps = raw_market.get("gaps")
        open_gap = (
            gaps[open_index]
            if isinstance(gaps, list)
            and type(open_index) is int
            and 0 <= open_index < len(gaps)
            else None
        )
        subscription_attempts = raw_market.get("subscription_attempts")
        accepted = raw_market.get("accepted")
        gaps_dropped = raw_market.get("gaps_dropped")
        recorded_gaps = gaps if isinstance(gaps, list) else []
        result[str(coin)] = {
            "received": raw_market.get("received"),
            "candidate_l2_frames": raw_market.get("candidate_frames"),
            "accepted": raw_market.get("accepted"),
            "rejected": raw_market.get("rejected"),
            "duplicates": raw_market.get("duplicates"),
            "l2_gap_epoch": raw_market.get("l2_gap_epoch"),
            "rejected_by_reason": dict(raw_market.get("rejected_by_reason", {}))
            if isinstance(raw_market.get("rejected_by_reason"), Mapping)
            else None,
            "ignored_by_reason": dict(raw_market.get("ignored_by_reason", {}))
            if isinstance(raw_market.get("ignored_by_reason"), Mapping)
            else None,
            "subscription_status": raw_market.get("subscription_status"),
            "subscription_attempts": [
                {key: value for key, value in attempt.items() if not key.startswith("_")}
                for attempt in subscription_attempts
                if isinstance(attempt, Mapping)
            ]
            if isinstance(subscription_attempts, list)
            else None,
            "subscription_attempts_dropped": raw_market.get(
                "subscription_attempts_dropped"
            ),
            "last_receive_ts_ms": last_receive,
            "last_receive_age_ms": age,
            "last_exchange_ts_ms": raw_market.get("last_exchange_ts_ms"),
            "last_connection_id": raw_market.get("last_connection_id"),
            "sequence_continuity_proven": False,
            "coverage_status": (
                "GAP_OPEN"
                if isinstance(open_gap, Mapping)
                else (
                    "SNAPSHOTS_CONTINUITY_UNPROVEN"
                    if type(raw_market.get("accepted")) is int
                    and raw_market["accepted"] > 0
                    else "NO_SNAPSHOT"
                )
            ),
            "proof_window_status": (
                "UNAVAILABLE"
                if isinstance(open_gap, Mapping)
                or bool(recorded_gaps)
                or (type(gaps_dropped) is int and gaps_dropped > 0)
                or type(accepted) is not int
                or accepted <= 0
                else "UNPROVEN"
            ),
            "open_gap": dict(open_gap) if isinstance(open_gap, Mapping) else None,
            "gaps": [dict(gap) for gap in gaps if isinstance(gap, Mapping)]
            if isinstance(gaps, list)
            else [],
            "gaps_dropped": raw_market.get("gaps_dropped"),
        }
    return result


def _l2_diagnostics(
    state: Mapping[str, Any],
    *,
    end_ms: int,
    requested_coins: set[str],
) -> dict[str, Any]:
    def counter(key: str) -> int | None:
        value = state.get(key)
        return value if type(value) is int and value >= 0 else None

    def counter_map(key: str) -> dict[str, int] | None:
        value = state.get(key)
        if not isinstance(value, Mapping):
            return None
        if any(type(count) is not int or count < 0 for count in value.values()):
            return None
        return {str(reason): count for reason, count in value.items()}

    markets = _l2_market_summary(state, end_ms)
    for coin in sorted({canonical_copy_vault_coin(item) for item in requested_coins}):
        if coin and coin not in markets:
            markets[coin] = {
                "received": None,
                "candidate_l2_frames": None,
                "accepted": None,
                "rejected": None,
                "duplicates": None,
                "rejected_by_reason": None,
                "ignored_by_reason": None,
                "subscription_status": "UNKNOWN",
                "subscription_attempts": None,
                "subscription_attempts_dropped": None,
                "last_receive_ts_ms": None,
                "last_receive_age_ms": None,
                "last_exchange_ts_ms": None,
                "last_connection_id": None,
                "sequence_continuity_proven": False,
                "coverage_status": "NO_MARKET_STATE",
                "proof_window_status": "UNAVAILABLE",
                "l2_gap_epoch": None,
                "open_gap": None,
                "gaps": [],
                "gaps_dropped": None,
            }
    ignored_by_reason = counter_map("ignored_by_reason")
    ignored_frames = (
        sum(ignored_by_reason.values())
        if ignored_by_reason is not None
        else None
    )
    connection_events = state.get("connection_events")
    unknown_rejections = state.get("unknown_market_rejections")
    required_markets = sorted(
        {
            canonical_copy_vault_coin(item)
            for item in requested_coins
            if canonical_copy_vault_coin(item)
        }
    )
    required_statuses = [
        markets[coin].get("proof_window_status")
        for coin in required_markets
        if isinstance(markets.get(coin), Mapping)
    ]
    required_window_status = (
        "UNMEASURABLE"
        if not required_markets or len(required_statuses) != len(required_markets)
        else (
            "UNAVAILABLE"
            if "UNAVAILABLE" in required_statuses
            else "UNPROVEN"
        )
    )
    return {
        "received_frames": counter("received"),
        "candidate_l2_frames": counter("candidate_frames"),
        "accepted_frames": counter("frames"),
        "rejected_frames": counter("rejected"),
        "rejected_by_reason": counter_map("rejected_by_reason"),
        "ignored_frames": ignored_frames,
        "ignored_by_reason": ignored_by_reason,
        "duplicate_snapshots": counter("duplicates"),
        "reconnects": counter("reconnects"),
        "heartbeats_sent": counter("heartbeats"),
        "heartbeats_received": counter("heartbeats_received"),
        "subscription_ack_mismatches": counter("subscription_ack_mismatches"),
        "invalid_subscription_acks": counter("invalid_subscription_acks"),
        "same_connection_market_stream": {
            "channels": list(COPY_VAULT_MARKET_CHANNEL_TYPES),
            "instrument_cap": MAX_COPY_VAULT_MARKET_INSTRUMENTS,
            "subscriptions_requested": counter("market_subscription_requested"),
            "subscriptions_acknowledged": counter("market_acknowledged"),
            "instruments_omitted_by_cap": counter("market_cap_omitted_coins"),
            "frames_accepted_by_channel": counter_map("market_accepted_by_channel"),
            "frames_rejected_by_reason": counter_map("market_rejected_by_reason"),
            "subscription_rejections": counter_map("market_subscription_rejections"),
        },
        "requested_markets": required_markets,
        "required_market_proof_window_status": required_window_status,
        "markets": markets,
        "connection_events": [
            dict(event)
            for event in connection_events
            if isinstance(connection_events, list) and isinstance(event, Mapping)
        ]
        if isinstance(connection_events, list)
        else None,
        "connection_events_dropped": counter("connection_events_dropped"),
        "unknown_market_rejections": [
            dict(event)
            for event in unknown_rejections
            if isinstance(unknown_rejections, list) and isinstance(event, Mapping)
        ]
        if isinstance(unknown_rejections, list)
        else None,
        "unknown_market_rejections_dropped": counter(
            "unknown_market_rejections_dropped"
        ),
        "coverage_claim": "NOT_PROVEN",
        "freshness_policy": "AGE_REPORTED_NO_THRESHOLD_ASSUMED",
    }


def _l2_payload_coin(message: Mapping[str, Any]) -> str | None:
    data = message.get("data")
    if not isinstance(data, Mapping):
        return None
    coin = canonical_copy_vault_coin(data.get("coin"))
    return coin or None


def l2_envelope(
    message: Mapping[str, Any],
    *,
    receive_wall_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    reconnect_count: int = 0,
    l2_gap_epoch: int = 0,
) -> TickEnvelope | None:
    reason, coin = _l2_message_status(message)
    if reason is not None or coin is None:
        return None
    data = message.get("data")
    assert isinstance(data, Mapping)
    exchange_ts_ms = int(data["time"])
    levels = data.get("levels")
    assert isinstance(levels, list) and len(levels) == 2
    bid_levels, ask_levels = len(levels[0]), len(levels[1])
    return TickEnvelope(
        source_id="hyperliquid_public_copy_l2",
        channel="copy_vault_l2",
        instrument=coin,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload=dict(message),
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=receive_wall_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=connection_id,
        reconnect_count=int(reconnect_count),
        provenance={
            "url": WS_URL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
            "copy_vault_execution_evidence": True,
        },
        parsed_summary={
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
            "l2_gap_epoch": l2_gap_epoch,
            "data_gate_ready": False,
        },
    )


def _finite_market_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _unknown_market_envelope(
    message: Mapping[str, Any], *, receive_wall_ms: int, receive_mono_ns: int,
    connection_id: str, reconnect_count: int, reason: str,
) -> TickEnvelope:
    data = message.get("data")
    coin = str(data.get("coin") or "").strip() if isinstance(data, Mapping) else "*"
    return TickEnvelope(
        source_id="hyperliquid_public_copy_vault_market_ws",
        channel="copy_vault_unknown",
        instrument=coin or "*",
        event_kind="UNCLASSIFIED",
        raw_payload=dict(message),
        received_ts_ms=int(receive_wall_ms),
        local_monotonic_ns=int(receive_mono_ns),
        connection_id=connection_id,
        reconnect_count=int(reconnect_count),
        provenance={
            "url": WS_URL, "network": "mainnet", "venue": "hyperliquid",
            "access": "read_only", "transport": "websocket",
            "authenticated": False,
            "timestamp_semantics": "receive_observation_time_only",
        },
        parsed_summary={"unclassified_reason": reason, "data_gate_ready": False},
    )


def copy_vault_accounting_envelopes(
    message: Mapping[str, Any], *, vault: str, receive_wall_ms: int,
    receive_mono_ns: int, connection_id: str, reconnect_count: int = 0,
) -> tuple[list[TickEnvelope], str | None]:
    """Preserve causal public funding/ledger events without treating them as PnL."""
    channel = str(message.get("channel") or "")
    data = message.get("data")
    vault_id = str(vault or "").strip().lower()
    if channel not in {"userFundings", "userNonFundingLedgerUpdates"}:
        return [], "UNSUPPORTED_ACCOUNTING_CHANNEL"
    if not isinstance(data, Mapping) or str(data.get("user") or "").lower() != vault_id:
        return [], "ACCOUNTING_USER_MISMATCH_OR_PAYLOAD_INVALID"
    snapshot = data.get("isSnapshot")
    if type(snapshot) is not bool:
        return [], "ACCOUNTING_SNAPSHOT_FLAG_UNCLASSIFIED"
    if channel == "userFundings":
        rows_value = data.get("fundings")
        family = "copy_vault_funding"
        row_key = "fundings"
    else:
        rows_value = data.get("nonFundingLedgerUpdates")
        family = "copy_vault_ledger"
        row_key = "nonFundingLedgerUpdates"
    if not isinstance(rows_value, list):
        return [], "ACCOUNTING_EVENT_LIST_MISSING"

    output: list[TickEnvelope] = []
    invalid_rows: list[Any] = []
    for row in rows_value:
        if not isinstance(row, Mapping):
            invalid_rows.append(row)
            continue
        event_time = row.get("time")
        if type(event_time) is not int or event_time <= 0 or event_time > receive_wall_ms:
            invalid_rows.append(dict(row))
            continue
        if channel == "userFundings":
            coin = canonical_copy_vault_coin(row.get("coin"))
            try:
                values = [
                    Decimal(str(row[key]))
                    for key in ("usdc", "szi", "fundingRate")
                ]
            except (KeyError, InvalidOperation, TypeError, ValueError):
                invalid_rows.append(dict(row))
                continue
            if not coin or not all(value.is_finite() for value in values):
                invalid_rows.append(dict(row))
                continue
        else:
            delta = row.get("delta")
            if (
                not str(row.get("hash") or "").strip()
                or not isinstance(delta, Mapping)
                or not str(delta.get("type") or "").strip()
            ):
                invalid_rows.append(dict(row))
                continue
        row_message = {
            "channel": channel,
            "data": {
                "user": vault_id,
                "isSnapshot": snapshot,
                row_key: [dict(row)],
            },
        }
        output.append(TickEnvelope(
            source_id=(
                "hl_public_account"
                if channel == "userFundings"
                else "hl_public_account"
            ),
            channel=family,
            instrument=vault_id,
            event_kind=FeedEventKind.SNAPSHOT if snapshot else FeedEventKind.EVENT,
            raw_payload=row_message,
            exchange_ts_ms=event_time,
            received_ts_ms=int(receive_wall_ms),
            local_monotonic_ns=int(receive_mono_ns),
            connection_id=connection_id,
            reconnect_count=int(reconnect_count),
            provenance={
                "url": WS_URL, "network": "mainnet", "access": "read_only",
                "venue": "hyperliquid", "transport": "websocket",
                "authenticated": False,
                "timestamp_semantics": "causal_event_availability",
                "snapshot_only_research": bool(snapshot),
                "forward_evidence_allowed": False,
            },
            parsed_summary={
                "event_count": 1,
                "is_snapshot": snapshot,
                "accounting_event_type": (
                    "funding" if channel == "userFundings"
                    else str(row["delta"]["type"])
                ),
                "data_gate_ready": False,
                "proof_of_pnl_allowed": False,
            },
        ))
    if invalid_rows:
        return output, "ACCOUNTING_ROWS_INVALID"
    if not rows_value:
        # An empty initial snapshot proves only that the feed emitted no rows at
        # that instant; it is not evidence of zero funding or zero ledger change.
        output.append(TickEnvelope(
            source_id=(
                "hl_public_account"
                if channel == "userFundings"
                else "hl_public_account"
            ),
            channel=family,
            instrument=vault_id,
            event_kind=FeedEventKind.SNAPSHOT,
            raw_payload=dict(message),
            received_ts_ms=int(receive_wall_ms),
            local_monotonic_ns=int(receive_mono_ns),
            connection_id=connection_id,
            reconnect_count=int(reconnect_count),
            provenance={
                "url": WS_URL, "network": "mainnet", "access": "read_only",
                "venue": "hyperliquid", "transport": "websocket",
                "authenticated": False,
                "timestamp_semantics": "receive_observation_time_only",
                "snapshot_only_research": True,
                "forward_evidence_allowed": False,
            },
            parsed_summary={
                "event_count": 0, "is_snapshot": True,
                "empty_snapshot_is_zero_proof": False,
                "data_gate_ready": False, "proof_of_pnl_allowed": False,
            },
        ))
    return output, None


def copy_vault_market_subscriptions(coin: str) -> list[dict[str, str]]:
    native_coin = str(coin or "").strip()
    if not native_coin:
        return []
    return [
        {"type": channel_type, "coin": native_coin}
        for channel_type in COPY_VAULT_MARKET_CHANNEL_TYPES
    ]


def market_subscription_ack_key(message: Mapping[str, Any]) -> tuple[str, str] | None:
    if message.get("channel") != "subscriptionResponse":
        return None
    data = message.get("data")
    if (
        not isinstance(data, Mapping) or data.get("method") != "subscribe"
        or data.get("error") is not None or message.get("error") is not None
    ):
        return None
    subscription = data.get("subscription")
    if not isinstance(subscription, Mapping):
        return None
    kind = str(subscription.get("type") or "").strip()
    coin = str(subscription.get("coin") or "").strip()
    return (kind, coin) if kind in COPY_VAULT_MARKET_CHANNEL_TYPES and coin else None


def copy_vault_market_envelopes(
    message: Mapping[str, Any], *, receive_wall_ms: int, receive_mono_ns: int,
    connection_id: str, reconnect_count: int = 0,
) -> list[TickEnvelope]:
    """Keep validated Copy-Vault BBO/trades/context; quarantine invalid frames."""
    channel = str(message.get("channel") or "")
    if channel == "l2Book":
        envelope = l2_envelope(
            message, receive_wall_ms=receive_wall_ms,
            receive_mono_ns=receive_mono_ns, connection_id=connection_id,
            reconnect_count=reconnect_count,
        )
        return [envelope] if envelope is not None else [_unknown_market_envelope(
            message, receive_wall_ms=receive_wall_ms, receive_mono_ns=receive_mono_ns,
            connection_id=connection_id, reconnect_count=reconnect_count,
            reason="L2_PAYLOAD_OR_CAUSAL_CLOCK_INVALID",
        )]
    if channel not in {"bbo", "trades", "activeAssetCtx"}:
        return []
    data = message.get("data")
    if channel == "trades":
        if not isinstance(data, list):
            return [_unknown_market_envelope(
                message, receive_wall_ms=receive_wall_ms, receive_mono_ns=receive_mono_ns,
                connection_id=connection_id, reconnect_count=reconnect_count,
                reason="TRADE_PAYLOAD_NOT_LIST",
            )]
        output: list[TickEnvelope] = []
        invalid: list[Any] = []
        for row in data:
            if not isinstance(row, Mapping):
                invalid.append(row)
                continue
            coin = str(row.get("coin") or "").strip()
            ts = row.get("time")
            px, sz = _finite_market_number(row.get("px")), _finite_market_number(row.get("sz"))
            identity = bool(str(row.get("hash") or "").strip()) or type(row.get("tid")) is int
            if (
                not coin or type(ts) is not int or ts <= 0 or ts > receive_wall_ms
                or receive_wall_ms - ts > 30_000 or not identity
                or px is None or px <= 0 or sz is None or sz <= 0
                or str(row.get("side") or "").upper() not in {"A", "B"}
            ):
                invalid.append(dict(row))
                continue
            output.append(TickEnvelope(
                source_id="hyperliquid_public_copy_vault_market_ws",
                channel="copy_vault_trades", instrument=coin,
                event_kind=FeedEventKind.EVENT,
                raw_payload={"channel": "trades", "data": [dict(row)]},
                exchange_ts_ms=ts, received_ts_ms=int(receive_wall_ms),
                local_monotonic_ns=int(receive_mono_ns), connection_id=connection_id,
                reconnect_count=int(reconnect_count),
                provenance={
                    "url": WS_URL, "network": "mainnet", "venue": "hyperliquid",
                    "access": "read_only", "transport": "websocket",
                    "authenticated": False,
                    "timestamp_semantics": "causal_event_availability",
                    "copy_vault_same_run_market_evidence": True,
                },
                parsed_summary={"event_count": 1, "data_gate_ready": False},
            ))
        if invalid:
            output.append(_unknown_market_envelope(
                {"channel": "trades", "data": invalid},
                receive_wall_ms=receive_wall_ms, receive_mono_ns=receive_mono_ns,
                connection_id=connection_id, reconnect_count=reconnect_count,
                reason="TRADE_ROW_MISSING_NATIVE_IDENTITY_OR_PRICE_SIZE_TIME",
            ))
        return output

    if not isinstance(data, Mapping):
        reason = "MARKET_DATA_NOT_OBJECT"
        coin = ""
    else:
        coin = str(data.get("coin") or "").strip()
        ts = data.get("time")
        reason = ""
        if not coin:
            reason = "MARKET_INSTRUMENT_MISSING"
        elif channel == "activeAssetCtx":
            if not isinstance(data.get("ctx"), Mapping) or ts is not None:
                reason = "ACTIVE_ASSET_CONTEXT_INVALID"
        else:
            bbo = data.get("bbo")
            if (
                type(ts) is not int or ts <= 0 or ts > receive_wall_ms
                or receive_wall_ms - ts > 30_000
                or not isinstance(bbo, list) or len(bbo) != 2
                or not all(isinstance(level, Mapping) for level in bbo)
            ):
                reason = "BBO_PAYLOAD_OR_CAUSAL_CLOCK_INVALID"
            else:
                prices = [_finite_market_number(level.get("px")) for level in bbo]
                sizes = [_finite_market_number(level.get("sz")) for level in bbo]
                if (
                    any(value is None for value in prices + sizes)
                    or prices[0] is None or prices[1] is None
                    or sizes[0] is None or sizes[1] is None
                    or prices[0] <= 0 or prices[1] <= prices[0]
                    or sizes[0] < 0 or sizes[1] < 0
                ):
                    reason = "BBO_PRICE_SIZE_OR_SPREAD_INVALID"
    if reason:
        return [_unknown_market_envelope(
            message, receive_wall_ms=receive_wall_ms, receive_mono_ns=receive_mono_ns,
            connection_id=connection_id, reconnect_count=reconnect_count, reason=reason,
        )]
    observation_only = channel == "activeAssetCtx"
    return [TickEnvelope(
        source_id="hyperliquid_public_copy_vault_market_ws",
        channel={
            "bbo": "copy_vault_bbo",
            "activeAssetCtx": "copy_vault_active_asset_ctx",
        }[channel],
        instrument=coin,
        event_kind=FeedEventKind.SNAPSHOT if channel == "bbo" else FeedEventKind.INCREMENTAL,
        raw_payload=dict(message),
        exchange_ts_ms=None if observation_only else ts,
        received_ts_ms=int(receive_wall_ms), local_monotonic_ns=int(receive_mono_ns),
        connection_id=connection_id, reconnect_count=int(reconnect_count),
        provenance={
            "url": WS_URL, "network": "mainnet", "venue": "hyperliquid",
            "access": "read_only", "transport": "websocket", "authenticated": False,
            "timestamp_semantics": (
                "receive_observation_time_only" if observation_only
                else "causal_event_availability"
            ),
            "copy_vault_same_run_market_evidence": True,
        },
        parsed_summary={
            "event_count": 1, "observation_only": observation_only,
            "data_gate_ready": False,
        },
    )]


async def _dynamic_l2_collector(
    sink: AsyncTickSink,
    request_queue: asyncio.Queue[str],
    known_coins: set[str],
    state: dict[str, Any],
) -> None:
    """Maintain one public HL L2 socket and dynamically subscribe leader coins."""
    attempt = 0
    while True:
        connection_id = f"copy-l2-{uuid.uuid4().hex}"
        requested: set[str] = set()
        subscribed: set[str] = set()
        market_coin_requests: set[str] = set()
        market_requested: set[tuple[str, str]] = set()
        market_subscribed: set[tuple[str, str]] = set()
        market_omitted: set[str] = set()
        attempts: list[dict[str, Any]] = []
        current_by_coin: dict[str, dict[str, Any]] = {}
        stop_watchdog = asyncio.Event()
        watchdog_task: asyncio.Task[Any] | None = None

        def invalidate_attempts(
            reason: str,
            *,
            _current_by_coin: dict[str, dict[str, Any]] = current_by_coin,
        ) -> None:
            at_ms = int(time.time() * 1_000)
            for coin, current in _current_by_coin.items():
                if _invalidate_subscription_attempt(
                    current, at_ms=at_ms, reason=reason
                ):
                    _l2_market_state(state, coin)["subscription_status"] = (
                        "INVALIDATED"
                    )

        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                send_lock = asyncio.Lock()
                connection_started_ms = int(time.time() * 1_000)
                _append_l2_history(
                    state,
                    "connection_events",
                    {
                        "event": "connected",
                        "time_ms": connection_started_ms,
                        "connection_id": connection_id,
                        "markets": sorted(known_coins),
                    },
                )

                async def send_json(
                    payload: Mapping[str, Any],
                    *,
                    _send_lock: asyncio.Lock = send_lock,
                    _socket: Any = socket,
                ) -> None:
                    async with _send_lock:
                        await _socket.send(json.dumps(dict(payload)))

                async def subscribe_coin(
                    coin: str,
                    *,
                    _current_by_coin: dict[str, dict[str, Any]] = current_by_coin,
                    _connection_id: str = connection_id,
                    _attempts: list[dict[str, Any]] = attempts,
                    _requested: set[str] = requested,
                    _market_coin_requests: set[str] = market_coin_requests,
                    _market_requested: set[tuple[str, str]] = market_requested,
                    _market_omitted: set[str] = market_omitted,
                    _send_json: Any = send_json,
                ) -> None:
                    normalized_coin = canonical_copy_vault_coin(coin)
                    if not normalized_coin:
                        return
                    if normalized_coin not in _market_coin_requests:
                        if len(_market_coin_requests) >= MAX_COPY_VAULT_MARKET_INSTRUMENTS:
                            if normalized_coin not in _market_omitted:
                                _market_omitted.add(normalized_coin)
                                state["market_cap_omitted_coins"] = int(
                                    state.get("market_cap_omitted_coins", 0)
                                ) + 1
                            return
                        _market_coin_requests.add(normalized_coin)
                    current = _current_by_coin.get(normalized_coin)
                    if current is not None and current.get("status") in {
                        "PENDING",
                        "ACTIVE",
                        "TIMED_OUT",
                    }:
                        return
                    subscription = {"type": "l2Book", "coin": normalized_coin}
                    sent_wall_ms = int(time.time() * 1_000)
                    subscription_attempt = _new_subscription_attempt(
                        subscription,
                        connection_id=_connection_id,
                        sent_at_ms=sent_wall_ms,
                        sent_monotonic=time.monotonic(),
                    )
                    _current_by_coin[normalized_coin] = subscription_attempt
                    _attempts.append(subscription_attempt)
                    _requested.add(normalized_coin)
                    market = _l2_market_state(state, normalized_coin)
                    history = market["subscription_attempts"]
                    history.append(subscription_attempt)
                    overflow = max(
                        0, len(history) - MAX_L2_DIAGNOSTIC_RECORDS
                    )
                    if overflow:
                        del history[:overflow]
                        market["subscription_attempts_dropped"] += overflow
                    market["subscription_status"] = "PENDING"
                    try:
                        await _send_json(
                            {"method": "subscribe", "subscription": subscription}
                        )
                        for market_subscription in copy_vault_market_subscriptions(
                            normalized_coin
                        ):
                            if market_subscription["type"] == "l2Book":
                                continue
                            key = (
                                market_subscription["type"],
                                market_subscription["coin"],
                            )
                            await _send_json(
                                {
                                    "method": "subscribe",
                                    "subscription": market_subscription,
                                }
                            )
                            _market_requested.add(key)
                            state["market_subscription_requested"] = int(
                                state.get("market_subscription_requested", 0)
                            ) + 1
                    except Exception as exc:
                        subscription_attempt["status"] = "SEND_FAILED"
                        subscription_attempt["error"] = type(exc).__name__
                        market["subscription_status"] = "SEND_FAILED"
                        raise

                def on_subscription_timeout(
                    subscription_attempt: Mapping[str, Any],
                    *,
                    _connection_id: str = connection_id,
                ) -> None:
                    coin = str(subscription_attempt.get("identity") or "")
                    if coin:
                        _l2_market_state(state, coin)["subscription_status"] = (
                            "TIMED_OUT"
                        )
                        _open_l2_gap(
                            state,
                            coin,
                            reason="subscription_ack_timeout",
                            at_ms=int(time.time() * 1_000),
                            connection_id=_connection_id,
                        )

                for coin in sorted(known_coins):
                    await subscribe_coin(coin)
                    await asyncio.sleep(0.03)

                async def sender(
                    *,
                    _request_queue: asyncio.Queue[str] = request_queue,
                    _requested: set[str] = requested,
                    _subscribe_coin: Any = subscribe_coin,
                ) -> None:
                    while True:
                        coin = canonical_copy_vault_coin(await _request_queue.get())
                        try:
                            if coin and coin not in _requested:
                                await _subscribe_coin(coin)
                        finally:
                            _request_queue.task_done()

                async def heartbeat(*, _send_json: Any = send_json) -> None:
                    while True:
                        await asyncio.sleep(30.0)
                        await _send_json({"method": "ping"})
                        state["heartbeats"] = state.get("heartbeats", 0) + 1

                sender_task: asyncio.Task[Any] | None = None
                heartbeat_task: asyncio.Task[Any] | None = None
                try:
                    sender_task = asyncio.create_task(sender())
                    heartbeat_task = asyncio.create_task(heartbeat())
                    watchdog_task = asyncio.create_task(
                        _subscription_timeout_watchdog(
                            attempts, stop_watchdog, on_subscription_timeout
                        )
                    )
                    attempt = 0
                    async for raw_text in socket:
                        mono = time.monotonic_ns()
                        wall = int(time.time() * 1_000)
                        state["received"] = int(state.get("received", 0)) + 1
                        try:
                            raw_message = json.loads(raw_text)
                        except (TypeError, ValueError):
                            raw_message = None
                        if isinstance(raw_message, Mapping):
                            channel = str(raw_message.get("channel") or "")
                            if channel == "pong":
                                _record_l2_ignored(state, "pong")
                                state["heartbeats_received"] = int(
                                    state.get("heartbeats_received", 0)
                                ) + 1
                                continue
                            if channel == "subscriptionResponse":
                                ack = classify_subscription_ack(raw_message)
                                if ack is None or ack[0] == "INVALID":
                                    state["invalid_subscription_acks"] = int(
                                        state.get("invalid_subscription_acks", 0)
                                    ) + 1
                                    _record_l2_ignored(
                                        state, "invalid_subscription_ack"
                                    )
                                    continue
                                ack_status, identity, ack_error = ack
                                if identity is None:
                                    state["subscription_ack_mismatches"] = int(
                                        state.get("subscription_ack_mismatches", 0)
                                    ) + 1
                                    _record_l2_ignored(
                                        state, "unmatched_subscription_ack"
                                    )
                                    continue
                                if identity[0] != "l2Book":
                                    key = (identity[0], identity[1])
                                    if key not in market_requested:
                                        state["subscription_ack_mismatches"] = int(
                                            state.get("subscription_ack_mismatches", 0)
                                        ) + 1
                                        _record_l2_ignored(
                                            state, "unmatched_market_subscription_ack"
                                        )
                                    elif ack_status == "REJECTED":
                                        rejections = state.setdefault(
                                            "market_subscription_rejections", {}
                                        )
                                        reason = f"{key[0]}:{ack_error or 'rejected'}"
                                        rejections[reason] = int(
                                            rejections.get(reason, 0)
                                        ) + 1
                                        _record_l2_ignored(
                                            state, "market_subscription_rejected"
                                        )
                                    elif key in market_subscribed:
                                        _record_l2_ignored(
                                            state, "duplicate_market_subscription_ack"
                                        )
                                    else:
                                        market_subscribed.add(key)
                                        state["market_acknowledged"] = int(
                                            state.get("market_acknowledged", 0)
                                        ) + 1
                                        _record_l2_ignored(
                                            state, "market_subscription_acknowledged"
                                        )
                                    continue
                                coin = identity[1]
                                subscription_attempt = current_by_coin.get(coin)
                                if (
                                    subscription_attempt is None
                                    or subscription_attempt.get("connection_id")
                                    != connection_id
                                ):
                                    state["subscription_ack_mismatches"] = int(
                                        state.get("subscription_ack_mismatches", 0)
                                    ) + 1
                                    _record_l2_ignored(
                                        state, "unmatched_subscription_ack"
                                    )
                                    continue
                                if ack_status == "REJECTED":
                                    subscription_attempt["status"] = "REJECTED"
                                    subscription_attempt["error"] = ack_error
                                    _l2_market_state(state, coin)[
                                        "subscription_status"
                                    ] = "REJECTED"
                                    _record_l2_rejection(
                                        state,
                                        "subscription_rejected",
                                        coin=coin,
                                        at_ms=wall,
                                        connection_id=connection_id,
                                    )
                                    continue
                                if subscription_attempt.get("status") not in {
                                    "PENDING",
                                    "TIMED_OUT",
                                }:
                                    _record_l2_ignored(
                                        state, "duplicate_subscription_ack"
                                    )
                                    continue
                                subscription_attempt["late_ack"] = (
                                    subscription_attempt.get("status")
                                    == "TIMED_OUT"
                                )
                                subscription_attempt["status"] = "ACTIVE"
                                subscription_attempt["acknowledged_at_ms"] = wall
                                _l2_market_state(state, coin)[
                                    "subscription_status"
                                ] = "ACTIVE"
                                subscribed.add(coin)
                                _record_l2_ignored(
                                    state, "subscription_acknowledged"
                                )
                                continue
                            if channel in {"bbo", "trades", "activeAssetCtx"}:
                                data = raw_message.get("data")
                                if channel == "trades" and isinstance(data, list):
                                    first_trade = data[0] if data else None
                                    native_coin = (
                                        canonical_copy_vault_coin(first_trade.get("coin"))
                                        if isinstance(first_trade, Mapping)
                                        else ""
                                    )
                                    mixed_instruments = any(
                                        not isinstance(row, Mapping)
                                        or canonical_copy_vault_coin(row.get("coin"))
                                        != native_coin
                                        for row in data
                                    )
                                else:
                                    native_coin = (
                                        canonical_copy_vault_coin(data.get("coin"))
                                        if isinstance(data, Mapping)
                                        else ""
                                    )
                                    mixed_instruments = False
                                key = (channel, native_coin)
                                if (
                                    not native_coin
                                    or native_coin not in requested
                                    or key not in market_subscribed
                                    or mixed_instruments
                                ):
                                    if mixed_instruments:
                                        reason = "market_trade_instrument_mismatch"
                                    elif native_coin and key in market_requested:
                                        state["market_rejected_before_ack"] = int(
                                            state.get("market_rejected_before_ack", 0)
                                        ) + 1
                                        reason = "market_data_before_connection_ack"
                                    else:
                                        reason = "market_data_for_unrequested_instrument"
                                    rejected = state.setdefault(
                                        "market_rejected_by_reason", {}
                                    )
                                    rejected[reason] = int(rejected.get(reason, 0)) + 1
                                    continue
                                envelopes = copy_vault_market_envelopes(
                                    raw_message,
                                    receive_wall_ms=wall,
                                    receive_mono_ns=mono,
                                    connection_id=connection_id,
                                    reconnect_count=state.get("reconnects", 0),
                                )
                                for envelope in envelopes:
                                    if envelope.channel == "copy_vault_unknown":
                                        rejected = state.setdefault(
                                            "market_rejected_by_reason", {}
                                        )
                                        reason = str(
                                            envelope.parsed_summary.get(
                                                "unclassified_reason", "invalid_market_payload"
                                            )
                                        )
                                        rejected[reason] = int(rejected.get(reason, 0)) + 1
                                    await _emit_with_backpressure(sink, envelope)
                                    if envelope.channel != "copy_vault_unknown":
                                        accepted = state.setdefault(
                                            "market_accepted_by_channel", {}
                                        )
                                        accepted[channel] = int(
                                            accepted.get(channel, 0)
                                        ) + 1
                                continue
                        message, reason, coin = classify_l2_payload(raw_text)
                        if message is not None and message.get("channel") == "l2Book":
                            state["candidate_frames"] = int(
                                state.get("candidate_frames", 0)
                            ) + 1
                            candidate_coin = _l2_payload_coin(message)
                            if candidate_coin:
                                candidate_market = _l2_market_state(
                                    state, candidate_coin
                                )
                                candidate_market["candidate_frames"] = int(
                                    candidate_market.get("candidate_frames", 0)
                                ) + 1
                        if reason == "wrong_channel":
                            channel = str(message.get("channel") or "") if message else ""
                            coin = _l2_payload_coin(message) if message else None
                            _record_l2_rejection(
                                state,
                                "wrong_channel",
                                coin=coin,
                                at_ms=wall,
                                connection_id=connection_id,
                                affected_coins=(
                                    set(requested) if coin is None else None
                                ),
                            )
                            continue
                        if reason is not None:
                            affected = (
                                set(requested)
                                if coin is None
                                else None
                            )
                            _record_l2_rejection(
                                state,
                                reason,
                                coin=coin,
                                at_ms=wall,
                                connection_id=connection_id,
                                affected_coins=affected,
                            )
                            continue
                        assert message is not None and coin is not None
                        if coin not in subscribed:
                            _record_l2_rejection(
                                state,
                                "subscription_not_active",
                                coin=coin,
                                at_ms=wall,
                                connection_id=connection_id,
                            )
                            continue
                        envelope = l2_envelope(
                            message,
                            receive_wall_ms=wall,
                            receive_mono_ns=mono,
                            connection_id=connection_id,
                            reconnect_count=state.get("reconnects", 0),
                            l2_gap_epoch=int(
                                _l2_market_state(state, coin).get("l2_gap_epoch", 0)
                            ),
                        )
                        if envelope is None:
                            _record_l2_rejection(
                                state,
                                "other_schema",
                                coin=coin,
                                at_ms=wall,
                                connection_id=connection_id,
                            )
                            continue
                        snapshot_issue = _l2_snapshot_duplicate_or_invalid(
                            state, envelope
                        )
                        if snapshot_issue == "duplicate_snapshot":
                            _record_l2_duplicate(state, envelope)
                            continue
                        if snapshot_issue is not None:
                            _record_l2_rejection(
                                state,
                                snapshot_issue,
                                coin=coin,
                                at_ms=wall,
                                connection_id=connection_id,
                            )
                            continue
                        await _emit_with_backpressure(sink, envelope)
                        _record_l2_accepted(
                            state,
                            envelope,
                            receive_wall_ms=wall,
                        )
                finally:
                    stop_watchdog.set()
                    pending_tasks = [
                        task
                        for task in (sender_task, heartbeat_task, watchdog_task)
                        if task is not None
                    ]
                    for task in pending_tasks:
                        task.cancel()
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                    invalidate_attempts("connection_ended")
            _record_l2_disconnect(
                state,
                connection_id=connection_id,
                markets=requested,
                at_ms=int(time.time() * 1_000),
                error_class="normal_close",
            )
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1
        except asyncio.CancelledError:
            invalidate_attempts("collector_stopped")
            raise
        except Exception as exc:
            invalidate_attempts(type(exc).__name__)
            _record_l2_disconnect(
                state,
                connection_id=connection_id,
                markets=requested,
                at_ms=int(time.time() * 1_000),
                error_class=type(exc).__name__,
            )
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1


def validate_user_subscription_budget(vaults: list[str]) -> int:
    """Enforce Hyperliquid's per-IP unique user subscription ceiling."""
    unique = {
        str(vault).strip().lower()
        for vault in vaults
        if str(vault).strip()
    }
    count = len(unique)
    if count > MAX_UNIQUE_USERS_PER_IP:
        raise ValueError(
            f"Copy-Vault lane has {count} unique users; "
            f"Hyperliquid limit is {MAX_UNIQUE_USERS_PER_IP} per IP"
        )
    return count



class _RequestRateGate:
    """Monotonic request spacing shared by all broad-sweep workers."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = max(0.0, float(interval_s))
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_at)
            self._next_at = slot + self.interval_s
        delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)


def _position_fingerprint(state: Mapping[str, Any]) -> str:
    rows = []
    for raw in state.get("positions") or []:
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "coin": canonical_copy_vault_coin(raw.get("coin")),
                "szi": raw.get("szi"),
                "entryPx": raw.get("entryPx"),
                "levier": raw.get("levier"),
            }
        )
    rows.sort(key=lambda row: (row["coin"], str(row["szi"])))
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def broad_state_envelope(
    payload: Mapping[str, Any],
    *,
    vault: str,
    phase: str,
    receive_wall_ms: int,
    receive_mono_ns: int,
) -> tuple[TickEnvelope | None, dict[str, Any] | None]:
    """Normalize one broad clearinghouseState observation into one compact family.

    All broad-state records intentionally use instrument='*' so thousands of vaults
    stay in a small number of Dataset V2 shards instead of creating one release
    asset per vault. The exact vault address remains in raw/parsed evidence.
    """
    parsed = CV.parser_clearinghouse(dict(payload))
    if parsed is None:
        return None, None
    fingerprint = _position_fingerprint(parsed)
    try:
        exchange_ts_ms = int(payload.get("time")) if payload.get("time") is not None else None
    except (TypeError, ValueError, OverflowError):
        exchange_ts_ms = None
    summary = {
        "vault": str(vault).lower(),
        "phase": str(phase).upper(),
        "position_fingerprint": fingerprint,
        "nav_usd": parsed.get("nav_usd"),
        "expo_brute_usd": parsed.get("expo_brute_usd"),
        "expo_nette_usd": parsed.get("expo_nette_usd"),
        "levier": parsed.get("levier"),
        "n_positions": parsed.get("n_positions"),
        "data_gate_ready": False,
    }
    envelope = TickEnvelope(
        source_id="hyperliquid_public_info",
        channel="copy_vault_broad_state",
        instrument="*",
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={
            "vault": str(vault).lower(),
            "phase": str(phase).upper(),
            "clearinghouseState": dict(payload),
        },
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=receive_wall_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=None,
        sequence=None,
        provenance={
            "url": INFO_URL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "request_type": "clearinghouseState",
            "broad_sweep": True,
        },
        parsed_summary=summary,
    )
    return envelope, {**summary, "positions": parsed.get("positions") or []}


async def collect_broad_state(
    rows: list[Mapping[str, Any]],
    sink: AsyncTickSink,
    *,
    phase: str,
    request_interval_s: float = BROAD_SWEEP_REQUEST_INTERVAL_S,
    concurrency: int = BROAD_SWEEP_CONCURRENCY,
    http_client: httpx.AsyncClient | None = None,
    pacer: RestWeightPacer | None = None,
) -> dict[str, Any]:
    """Rate-budgeted complete-universe clearinghouseState sweep.

    The official clearinghouseState request weight is 2. Production spacing is
    deliberately below the per-IP 1200 weight/min limit. Failures remain visible
    and never fabricate state.
    """
    started = time.monotonic()
    gate = _RequestRateGate(request_interval_s)
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    )
    states: dict[str, dict[str, Any]] = {}
    failures: dict[str, int] = defaultdict(int)

    async def one(row: Mapping[str, Any]) -> None:
        vault = str(row.get("address") or "").strip().lower()
        if not vault:
            failures["MISSING_ADDRESS"] += 1
            return
        async with semaphore:
            last_error = "UNKNOWN"
            for attempt in range(2):
                if pacer is None:
                    await gate.wait()
                try:
                    if pacer is not None:
                        await pacer.acquire_weight(2)
                    response = await client.post(
                        "/info",
                        json={"type": "clearinghouseState", "user": vault},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    last_error = type(exc).__name__
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    failures[last_error] += 1
                    return
                if not isinstance(payload, Mapping):
                    failures["INVALID_PAYLOAD"] += 1
                    return
                receive_mono_ns = time.monotonic_ns()
                receive_wall_ms = int(time.time() * 1_000)
                envelope, state = broad_state_envelope(
                    payload,
                    vault=vault,
                    phase=phase,
                    receive_wall_ms=receive_wall_ms,
                    receive_mono_ns=receive_mono_ns,
                )
                if envelope is None or state is None:
                    failures["UNPARSABLE_STATE"] += 1
                    return
                state["tvl_usd"] = float(row.get("tvl_usd") or 0.0)
                states[vault] = state
                await _emit_with_backpressure(sink, envelope)
                return
            failures[last_error] += 1

    try:
        await asyncio.gather(*(one(row) for row in rows))
    finally:
        if owns_client:
            await client.aclose()

    return {
        "phase": str(phase).upper(),
        "requested": len(rows),
        "observed": len(states),
        "failed": max(0, len(rows) - len(states)),
        "failure_types": dict(sorted(failures.items())),
        "elapsed_s": round(time.monotonic() - started, 3),
        "request_interval_s": float(request_interval_s),
        "states": states,
    }


def select_priority_ws_vaults(
    rows: list[Mapping[str, Any]],
    broad_sweep: Mapping[str, Any],
    *,
    max_ws_vaults: int = MAX_PRIORITY_WS_VAULTS,
    rotation_seed: str = "",
) -> list[dict[str, Any]]:
    """Pick scarce WS users from broad state, plus deterministic audit rotation."""
    limit = max(1, min(MAX_PRIORITY_WS_VAULTS, int(max_ws_vaults)))
    states = broad_sweep.get("states")
    if not isinstance(states, Mapping) or not states:
        raise RuntimeError("broad Copy-Vault sweep produced no usable state")
    by_address = {
        str(row.get("address") or "").strip().lower(): dict(row)
        for row in rows
        if isinstance(row, Mapping) and str(row.get("address") or "").strip()
    }
    observed = [
        address for address in by_address
        if isinstance(states.get(address), Mapping)
    ]
    if not observed:
        raise RuntimeError("no frozen Copy-Vault address has observed broad state")

    audit_slots = min(PRIORITY_AUDIT_ROTATION_SLOTS, limit)
    core_slots = max(0, limit - audit_slots)

    def activity_key(address: str) -> tuple[float, float, float, str]:
        state = states[address]
        return (
            -float(state.get("n_positions") or 0),
            -float(state.get("expo_brute_usd") or 0.0),
            -float(by_address[address].get("tvl_usd") or 0.0),
            address,
        )

    active = [
        address for address in observed
        if int(states[address].get("n_positions") or 0) > 0
    ]
    active.sort(key=activity_key)
    selected = active[:core_slots]

    if len(selected) < core_slots:
        fill = [address for address in observed if address not in selected]
        fill.sort(key=activity_key)
        selected.extend(fill[: core_slots - len(selected)])

    remaining = [address for address in observed if address not in selected]
    remaining.sort(
        key=lambda address: hashlib.sha256(
            f"{rotation_seed}|{address}".encode()
        ).hexdigest()
    )
    selected.extend(remaining[: max(0, limit - len(selected))])

    result: list[dict[str, Any]] = []
    for index, address in enumerate(selected[:limit]):
        row = dict(by_address[address])
        state = states[address]
        row["ws_selection_reason"] = (
            "ACTIVE_PRIORITY" if address in active[:core_slots] else "AUDIT_ROTATION"
        )
        row["broad_n_positions"] = int(state.get("n_positions") or 0)
        row["broad_expo_brute_usd"] = float(state.get("expo_brute_usd") or 0.0)
        row["broad_position_fingerprint"] = str(
            state.get("position_fingerprint") or ""
        )
        row["ws_priority_rank"] = index
        result.append(row)
    return result


def _compact_sweep_metrics(sweep: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in sweep.items()
        if key != "states"
    }


async def collect_position_snapshots(
    vaults: list[str],
    sink: AsyncTickSink,
    *,
    phase: str,
    pacer: RestWeightPacer | None = None,
) -> int:
    """Capture public clearinghouse state as a leader-position anchor."""
    semaphore = asyncio.Semaphore(8)
    count = 0

    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        async def one(vault: str) -> TickEnvelope | None:
            async with semaphore:
                sent_ms = int(time.time() * 1_000)
                try:
                    if pacer is not None:
                        await pacer.acquire_weight(2)
                    response = await client.post(
                        "/info",
                        json={"type": "clearinghouseState", "user": vault},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    return None
                mono = time.monotonic_ns()
                received_ms = int(time.time() * 1_000)
                if not isinstance(payload, Mapping):
                    return None
                positions = payload.get("assetPositions")
                position_count = len(positions) if isinstance(positions, list) else 0
                return TickEnvelope(
                    source_id="hyperliquid_public_info",
                    channel="copy_vault_positions",
                    instrument=vault,
                    event_kind=FeedEventKind.SNAPSHOT,
                    raw_payload=dict(payload),
                    exchange_ts_ms=None,
                    received_ts_ms=received_ms,
                    local_monotonic_ns=mono,
                    connection_id=None,
                    provenance={
                        "url": INFO_URL,
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "request_type": "clearinghouseState",
                        "timestamp_semantics": "receive_observation_time_only",
                        "request_send_wall_ms": sent_ms,
                        "request_receive_wall_ms": received_ms,
                    },
                    parsed_summary={
                        "phase": phase,
                        "position_count": position_count,
                        "data_gate_ready": False,
                    },
                )

        rows = await asyncio.gather(*(one(vault) for vault in vaults))
        for envelope in rows:
            if envelope is not None:
                await _emit_with_backpressure(sink, envelope)
                count += 1
    return count


async def _socket_group(
    vaults: list[str],
    sink: AsyncTickSink,
    *,
    observation_start_ms: dict[str, int],
    live_ids: dict[str, set[str]],
    live_fill_counts: dict[str, int],
    unclassified_fill_counts: dict[str, int],
    reconnect_counts: dict[str, int],
    l2_request_queue: asyncio.Queue[str],
    l2_known_coins: set[str],
    subscription_attempts: dict[str, list[dict[str, Any]]],
    subscription_attempts_dropped: dict[str, int],
    subscription_diagnostics: dict[str, int],
    snapshot_fill_ids: dict[str, set[str]] | None = None,
) -> None:
    attempt = 0
    known = {vault.lower(): vault.lower() for vault in vaults}
    snapshot_fill_ids = snapshot_fill_ids if snapshot_fill_ids is not None else {}
    for vault in vaults:
        snapshot_fill_ids.setdefault(vault, set())
    while True:
        connection_id = f"copy-vault-{uuid.uuid4().hex}"
        connection_attempts: dict[tuple[str, str], dict[str, Any]] = {}
        attempts_for_watchdog: list[dict[str, Any]] = []
        stop_watchdog = asyncio.Event()
        watchdog_task: asyncio.Task[Any] | None = None
        heartbeat_task: asyncio.Task[Any] | None = None

        def invalidate_connection_attempts(
            reason: str,
            *,
            _connection_attempts: dict[
                tuple[str, str], dict[str, Any]
            ] = connection_attempts,
        ) -> None:
            at_ms = int(time.time() * 1_000)
            for (kind, _user), current in _connection_attempts.items():
                if _invalidate_subscription_attempt(
                    current, at_ms=at_ms, reason=reason
                ) and kind == "userFills":
                    subscription_diagnostics["invalidated_on_disconnect"] = (
                        subscription_diagnostics.get("invalidated_on_disconnect", 0)
                        + 1
                    )

        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                send_lock = asyncio.Lock()

                async def send_json(
                    payload: Mapping[str, Any],
                    *,
                    _send_lock: asyncio.Lock = send_lock,
                    _socket: Any = socket,
                ) -> None:
                    async with _send_lock:
                        await _socket.send(json.dumps(dict(payload)))

                for vault in vaults:
                    key = ("userFills", vault.lower())
                    history = subscription_attempts.setdefault(vault, [])
                    if history:
                        previous = history[-1]
                        if _invalidate_subscription_attempt(
                            previous,
                            at_ms=int(time.time() * 1_000),
                            reason="websocket_reconnect",
                        ):
                            subscription_diagnostics[
                                "invalidated_on_reconnect"
                            ] = subscription_diagnostics.get(
                                "invalidated_on_reconnect", 0
                            ) + 1
                    observation_start_ms.pop(vault, None)
                    live_ids[vault].clear()
                    live_fill_counts[vault] = 0
                    snapshot_fill_ids[vault].clear()
                    subscription = {"type": "userFills", "user": vault}
                    current = _new_subscription_attempt(
                        subscription,
                        connection_id=connection_id,
                        sent_at_ms=int(time.time() * 1_000),
                        sent_monotonic=time.monotonic(),
                    )
                    connection_attempts[key] = current
                    attempts_for_watchdog.append(current)
                    history.append(current)
                    overflow = max(
                        0, len(history) - MAX_L2_DIAGNOSTIC_RECORDS
                    )
                    if overflow:
                        del history[:overflow]
                        subscription_attempts_dropped[vault] = (
                            subscription_attempts_dropped.get(vault, 0) + overflow
                        )
                    try:
                        await send_json(
                            {"method": "subscribe", "subscription": subscription}
                        )
                    except Exception as exc:
                        current["status"] = "SEND_FAILED"
                        current["error"] = type(exc).__name__
                        raise
                    await asyncio.sleep(0.15)
                    for accounting_kind in (
                        "userFundings", "userNonFundingLedgerUpdates",
                    ):
                        accounting_subscription = {
                            "type": accounting_kind, "user": vault,
                        }
                        accounting_current = _new_subscription_attempt(
                            accounting_subscription,
                            connection_id=connection_id,
                            sent_at_ms=int(time.time() * 1_000),
                            sent_monotonic=time.monotonic(),
                        )
                        accounting_key = (accounting_kind, vault.lower())
                        connection_attempts[accounting_key] = accounting_current
                        attempts_for_watchdog.append(accounting_current)
                        try:
                            await send_json({
                                "method": "subscribe",
                                "subscription": accounting_subscription,
                            })
                        except Exception as exc:
                            accounting_current["status"] = "SEND_FAILED"
                            accounting_current["error"] = type(exc).__name__
                            raise
                        diag_key = f"{accounting_kind}_requested"
                        subscription_diagnostics[diag_key] = (
                            subscription_diagnostics.get(diag_key, 0) + 1
                        )
                        await asyncio.sleep(0.15)

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(30.0)
                        await send_json({"method": "ping"})

                attempt = 0
                try:
                    watchdog_task = asyncio.create_task(
                        _subscription_timeout_watchdog(
                            attempts_for_watchdog, stop_watchdog
                        )
                    )
                    heartbeat_task = asyncio.create_task(heartbeat())
                    async for raw_text in socket:
                        mono = time.monotonic_ns()
                        wall = int(time.time() * 1_000)
                        try:
                            message = json.loads(raw_text)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(message, Mapping):
                            continue
                        channel = str(message.get("channel") or "")
                        if channel == "pong":
                            continue
                        if channel == "subscriptionResponse":
                            ack = classify_subscription_ack(message)
                            if ack is None or ack[0] == "INVALID":
                                subscription_diagnostics["invalid_acks"] = (
                                    subscription_diagnostics.get("invalid_acks", 0)
                                    + 1
                                )
                                continue
                            ack_status, identity, ack_error = ack
                            current = (
                                connection_attempts.get(identity)
                                if identity is not None
                                else None
                            )
                            if current is None or current.get("connection_id") != connection_id:
                                subscription_diagnostics["unmatched_acks"] = (
                                    subscription_diagnostics.get("unmatched_acks", 0)
                                    + 1
                                )
                                continue
                            vault = identity[1]
                            if ack_status == "REJECTED":
                                current["status"] = "REJECTED"
                                current["error"] = ack_error
                                subscription_diagnostics["rejected_acks"] = (
                                    subscription_diagnostics.get("rejected_acks", 0)
                                    + 1
                                )
                                if identity[0] in {
                                    "userFundings", "userNonFundingLedgerUpdates",
                                }:
                                    diag_key = f"{identity[0]}_rejected_acks"
                                    subscription_diagnostics[diag_key] = (
                                        subscription_diagnostics.get(diag_key, 0) + 1
                                    )
                                continue
                            if current.get("status") not in {"PENDING", "TIMED_OUT"}:
                                subscription_diagnostics["duplicate_acks"] = (
                                    subscription_diagnostics.get("duplicate_acks", 0)
                                    + 1
                                )
                                continue
                            current["late_ack"] = current.get("status") == "TIMED_OUT"
                            current["status"] = "ACTIVE"
                            current["acknowledged_at_ms"] = wall
                            if identity[0] == "userFills":
                                observation_start_ms[vault] = wall
                                diag_key = "acknowledged"
                            else:
                                diag_key = f"{identity[0]}_acknowledged"
                            subscription_diagnostics[diag_key] = (
                                subscription_diagnostics.get(diag_key, 0) + 1
                            )
                            continue

                        if channel in {
                            "userFundings", "userNonFundingLedgerUpdates",
                        }:
                            data = message.get("data")
                            user = (
                                str(data.get("user") or "").lower()
                                if isinstance(data, Mapping)
                                else ""
                            )
                            vault = known.get(user)
                            key = (channel, user)
                            current = connection_attempts.get(key)
                            if vault is None or current is None or current.get("status") != "ACTIVE":
                                diag_key = f"{channel}_messages_before_ack_dropped"
                                subscription_diagnostics[diag_key] = (
                                    subscription_diagnostics.get(diag_key, 0) + 1
                                )
                                continue
                            envelopes, error = copy_vault_accounting_envelopes(
                                message,
                                vault=vault,
                                receive_wall_ms=wall,
                                receive_mono_ns=mono,
                                connection_id=connection_id,
                                reconnect_count=reconnect_counts.get(vault, 0),
                            )
                            if error is not None:
                                diag_key = f"{channel}_invalid_messages"
                                subscription_diagnostics[diag_key] = (
                                    subscription_diagnostics.get(diag_key, 0) + 1
                                )
                                quarantine = TickEnvelope(
                                    source_id="hyperliquid_public_copy_vault_accounting_ws",
                                    channel="copy_vault_unknown",
                                    instrument=vault,
                                    event_kind="UNCLASSIFIED",
                                    raw_payload=dict(message),
                                    received_ts_ms=wall,
                                    local_monotonic_ns=mono,
                                    connection_id=connection_id,
                                    reconnect_count=reconnect_counts.get(vault, 0),
                                    provenance={
                                        "url": WS_URL, "network": "mainnet",
                                        "access": "read_only", "venue": "hyperliquid",
                                        "transport": "websocket", "authenticated": False,
                                        "timestamp_semantics": "receive_observation_time_only",
                                    },
                                    parsed_summary={
                                        "unclassified_reason": error,
                                        "data_gate_ready": False,
                                        "proof_of_pnl_allowed": False,
                                    },
                                )
                                await _emit_with_backpressure(sink, quarantine)
                            for envelope in envelopes:
                                await _emit_with_backpressure(sink, envelope)
                            row_key = (
                                "user_funding_rows" if channel == "userFundings"
                                else "user_non_funding_ledger_rows"
                            )
                            subscription_diagnostics[row_key] = (
                                subscription_diagnostics.get(row_key, 0)
                                + sum(
                                    int(env.parsed_summary.get("event_count") or 0)
                                    for env in envelopes
                                )
                            )
                            continue

                        data = message.get("data")
                        user = (
                            str(data.get("user") or "").lower()
                            if isinstance(data, Mapping)
                            else ""
                        )
                        vault = known.get(user)
                        if vault is None:
                            continue
                        current = connection_attempts.get(("userFills", vault))
                        if current is None or current.get("status") != "ACTIVE":
                            subscription_diagnostics["messages_before_ack_dropped"] = (
                                subscription_diagnostics.get(
                                    "messages_before_ack_dropped", 0
                                )
                                + 1
                            )
                            continue

                        envelope, fills = userfills_envelope(
                            message,
                            vault=vault,
                            receive_wall_ms=wall,
                            receive_mono_ns=mono,
                            connection_id=connection_id,
                        )
                        if envelope is None:
                            continue
                        envelope.reconnect_count = reconnect_counts.get(vault, 0)
                        await _emit_with_backpressure(sink, envelope)
                        if envelope.parsed_summary.get("snapshot_flag_status") != "VALID":
                            unclassified_fill_counts[vault] += len(fills)

                        # Pre-warm public execution L2 from every observed coin,
                        # including the initial snapshot. Snapshot fills never count
                        # as forward copy signals.
                        for fill in fills:
                            coin = canonical_copy_vault_coin(fill.get("coin"))
                            if coin and coin not in l2_known_coins:
                                l2_known_coins.add(coin)
                                l2_request_queue.put_nowait(coin)

                        if envelope.parsed_summary.get("is_snapshot") is True:
                            for fill in fills:
                                fill_id = canonical_fill_id(fill)
                                if fill_id in snapshot_fill_ids[vault]:
                                    subscription_diagnostics[
                                        "duplicate_snapshot_fill_observed"
                                    ] = subscription_diagnostics.get(
                                        "duplicate_snapshot_fill_observed", 0
                                    ) + 1
                                snapshot_fill_ids[vault].add(fill_id)

                        # Selection time is only universe provenance. Forward
                        # reconciliation starts when this hosted lane can observe.
                        if (
                            envelope.channel != "copy_vault_fills"
                            or envelope.parsed_summary.get("snapshot_flag_status") != "VALID"
                            or envelope.parsed_summary.get("is_snapshot") is not False
                        ):
                            continue
                        for fill in fills:
                            try:
                                ts_ms = int(fill.get("ts_ms") or 0)
                            except (TypeError, ValueError, OverflowError):
                                continue
                            start_ms = observation_start_ms.get(vault)
                            if start_ms is None:
                                continue
                            fill_id = canonical_fill_id(fill)
                            if fill_id in snapshot_fill_ids[vault]:
                                subscription_diagnostics[
                                    "snapshot_stream_overlap_dropped"
                                ] = subscription_diagnostics.get(
                                    "snapshot_stream_overlap_dropped", 0
                                ) + 1
                                continue
                            if ts_ms <= int(start_ms):
                                if ts_ms == int(start_ms):
                                    subscription_diagnostics[
                                        "ambiguous_ack_boundary_fill_dropped"
                                    ] = subscription_diagnostics.get(
                                        "ambiguous_ack_boundary_fill_dropped", 0
                                    ) + 1
                                continue
                            if fill_id in live_ids[vault]:
                                subscription_diagnostics[
                                    "duplicate_stream_fill_dropped"
                                ] = subscription_diagnostics.get(
                                    "duplicate_stream_fill_dropped", 0
                                ) + 1
                                continue
                            live_ids[vault].add(fill_id)
                            live_fill_counts[vault] += 1
                finally:
                    stop_watchdog.set()
                    active_tasks = [
                        task
                        for task in (watchdog_task, heartbeat_task)
                        if task is not None
                    ]
                    for task in active_tasks:
                        task.cancel()
                    await asyncio.gather(*active_tasks, return_exceptions=True)
                    invalidate_connection_attempts("connection_ended")
        except asyncio.CancelledError:
            stop_watchdog.set()
            invalidate_connection_attempts("collector_stopped")
            raise
        except Exception:
            stop_watchdog.set()
            invalidate_connection_attempts("connection_error")
            for vault in vaults:
                reconnect_counts[vault] += 1
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1


async def _post_userfills(
    client: httpx.AsyncClient,
    vault: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    response = await client.post(
        "/info",
        json={
            "type": "userFillsByTime",
            "user": vault,
            "startTime": int(start_ms),
            "endTime": int(end_ms),
            "aggregateByTime": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("userFillsByTime returned non-list")
    return [row for row in payload if isinstance(row, dict)]


async def _post_user_accounting_history(
    client: httpx.AsyncClient,
    vault: str,
    *,
    request_type: str,
    start_ms: int,
    end_ms: int,
) -> list[Any]:
    if request_type not in {"userFunding", "userNonFundingLedgerUpdates"}:
        raise ValueError("unsupported Copy-Vault accounting history endpoint")
    response = await client.post(
        "/info",
        json={
            "type": request_type,
            "user": vault,
            "startTime": int(start_ms),
            "endTime": int(end_ms),
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"{request_type} returned non-list")
    return payload


def _accounting_history_row_valid(
    row: Any,
    *,
    request_type: str,
    start_ms: int,
    end_ms: int,
) -> bool:
    if not isinstance(row, Mapping):
        return False
    timestamp = row.get("time")
    if type(timestamp) is not int or not int(start_ms) <= timestamp <= int(end_ms):
        return False
    if request_type == "userFunding":
        delta = row.get("delta")
        detail = delta if isinstance(delta, Mapping) else row
        coin = canonical_copy_vault_coin(detail.get("coin"))
        try:
            numbers = [
                Decimal(str(detail[key]))
                for key in ("usdc", "szi", "fundingRate")
            ]
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return False
        return bool(coin) and all(number.is_finite() for number in numbers)
    delta = row.get("delta")
    return bool(
        str(row.get("hash") or "").strip()
        and isinstance(delta, Mapping)
        and str(delta.get("type") or "").strip()
    )


async def exact_window_accounting_backfill(
    client: httpx.AsyncClient,
    vault: str,
    *,
    request_type: str,
    start_ms: int,
    end_ms: int,
    min_window_ms: int = 1_000,
    max_requests: int = MAX_ACCOUNTING_BACKFILL_REQUESTS_PER_CHANNEL,
    pacer: RestWeightPacer | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch a bounded, exact account-event interval; capped windows stay partial."""
    if request_type not in {"userFunding", "userNonFundingLedgerUpdates"}:
        raise ValueError("unsupported Copy-Vault accounting history endpoint")
    if int(start_ms) <= 0 or int(end_ms) < int(start_ms):
        raise ValueError("invalid Copy-Vault accounting history interval")
    pending: deque[tuple[int, int]] = deque([(int(start_ms), int(end_ms))])
    accepted: dict[str, dict[str, Any]] = {}
    failed_windows: list[dict[str, Any]] = []
    cap_blocked_windows: list[dict[str, Any]] = []
    requests = splits = raw_event_count = invalid_event_count = 0
    request_budget_exhausted = False

    while pending:
        if requests >= max(1, int(max_requests)):
            request_budget_exhausted = True
            break
        left, right = pending.popleft()
        requests += 1
        try:
            if pacer is not None:
                await pacer.acquire_weight(MAX_TIME_RANGE_RESPONSE_WEIGHT)
            raw_rows = await _post_user_accounting_history(
                client,
                vault,
                request_type=request_type,
                start_ms=left,
                end_ms=right,
            )
        except Exception as exc:
            failed_windows.append({
                "start_ms": left,
                "end_ms": right,
                "error": type(exc).__name__,
            })
            continue

        capped = len(raw_rows) >= MAX_TIME_RANGE_RESPONSE_ROWS
        if capped and right - left > max(1, int(min_window_ms)):
            middle = left + (right - left) // 2
            pending.appendleft((middle + 1, right))
            pending.appendleft((left, middle))
            splits += 1
            continue
        raw_event_count += len(raw_rows)
        if capped:
            cap_blocked_windows.append({
                "start_ms": left,
                "end_ms": right,
                "rows": len(raw_rows),
                "cap": MAX_TIME_RANGE_RESPONSE_ROWS,
            })

        for row in raw_rows:
            if not _accounting_history_row_valid(
                row,
                request_type=request_type,
                start_ms=left,
                end_ms=right,
            ):
                invalid_event_count += 1
                continue
            assert isinstance(row, Mapping)
            event_hash = str(row.get("hash") or "").strip().lower()
            identity_material = json.dumps(
                row, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                default=str,
            )
            identity = event_hash or hashlib.sha256(
                identity_material.encode("utf-8")
            ).hexdigest()
            accepted[identity] = dict(row)

    unique_rows = sorted(
        accepted.values(),
        key=lambda row: (int(row["time"]), str(row.get("hash") or "")),
    )
    status = (
        "COMPLETE"
        if not failed_windows
        and not cap_blocked_windows
        and not request_budget_exhausted
        and not pending
        and invalid_event_count == 0
        else "PARTIAL"
    )
    return unique_rows, {
        "request_type": request_type,
        "status": status,
        "requested_start_ms": int(start_ms),
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "raw_event_count": raw_event_count,
        "event_count": len(unique_rows),
        "invalid_event_count": invalid_event_count,
        "duplicate_event_count": max(0, raw_event_count - invalid_event_count - len(unique_rows)),
        "failed_windows": failed_windows,
        "cap_blocked_windows": cap_blocked_windows,
        "request_budget_exhausted": request_budget_exhausted,
        "pending_windows": len(pending),
        "empty_result_is_zero_pnl_proof": False,
        "proof_of_pnl_allowed": False,
        "forward_evidence_allowed": False,
    }


def rest_accounting_backfill_envelopes(
    rows: list[Mapping[str, Any]],
    *,
    vault: str,
    request_type: str,
    audit: Mapping[str, Any],
    receive_wall_ms: int,
    receive_mono_ns: int,
) -> list[TickEnvelope]:
    """Preserve REST history in its own shard, separate from live WS ordering."""
    channel_by_request = {
        "userFunding": ("userFundings", "fundings", "copy_vault_funding"),
        "userNonFundingLedgerUpdates": (
            "userNonFundingLedgerUpdates",
            "nonFundingLedgerUpdates",
            "copy_vault_ledger",
        ),
    }
    if request_type not in channel_by_request:
        raise ValueError("unsupported Copy-Vault accounting history endpoint")
    if not vault or int(receive_wall_ms) <= 0 or int(receive_mono_ns) <= 0:
        raise ValueError("accounting history requires identity and receive clocks")
    raw_channel, row_key, family = channel_by_request[request_type]
    envelopes: list[TickEnvelope] = []
    for row in rows:
        if not _accounting_history_row_valid(
            row,
            request_type=request_type,
            start_ms=int(audit["requested_start_ms"]),
            end_ms=int(audit["requested_end_ms"]),
        ):
            raise ValueError("refusing to emit invalid accounting history event")
        assert isinstance(row, Mapping)
        event_ts_ms = int(row["time"])
        message = {
            "channel": raw_channel,
            "data": {
                "user": str(vault).lower(),
                # REST rows have no websocket snapshot bit; false preserves
                # that distinction while historical_only carries the real scope.
                "isSnapshot": False,
                row_key: [dict(row)],
            },
            "backfill_audit": dict(audit),
        }
        envelopes.append(TickEnvelope(
            source_id="hl_public_account_backfill",
            channel=family,
            instrument=str(vault).lower(),
            event_kind=FeedEventKind.EVENT,
            raw_payload=message,
            exchange_ts_ms=event_ts_ms,
            received_ts_ms=int(receive_wall_ms),
            local_monotonic_ns=int(receive_mono_ns),
            provenance={
                "url": INFO_URL,
                "network": "mainnet",
                "venue": "hyperliquid",
                "access": "read_only",
                "transport": "https",
                "authenticated": False,
                "request_type": request_type,
                "historical_only": True,
                "timestamp_semantics": "causal_event_availability",
                "backfill_status": str(audit.get("status") or "PARTIAL"),
                "forward_evidence_allowed": False,
            },
            parsed_summary={
                "event_count": 1,
                "is_snapshot": False,
                "historical_only": True,
                "proof_of_pnl_allowed": False,
                "backfill_complete": str(audit.get("status") or "").upper() == "COMPLETE",
            },
        ))
    return envelopes


async def exact_window_backfill(
    client: httpx.AsyncClient,
    vault: str,
    *,
    start_ms: int,
    end_ms: int,
    min_window_ms: int = 1_000,
    max_requests: int = MAX_RECONCILIATION_REQUESTS_PER_VAULT,
    pacer: RestWeightPacer | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Adaptive exact-window REST reconciliation using the 2,000 response cap."""
    pending: deque[tuple[int, int]] = deque([(int(start_ms), int(end_ms))])
    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    capped_minimum: list[dict[str, Any]] = []
    requests = 0
    splits = 0
    request_budget_exhausted = False
    invalid_fill_count = 0

    while pending:
        if requests >= max(1, int(max_requests)):
            request_budget_exhausted = True
            break
        left, right = pending.popleft()
        requests += 1
        try:
            if pacer is not None:
                await pacer.before_request()
            raw = await _post_userfills(client, vault, left, right)
        except Exception as exc:
            failures.append(
                {
                    "start_ms": left,
                    "end_ms": right,
                    "error": type(exc).__name__,
                }
            )
            continue
        if len(raw) >= CAP_USERFILLS:
            span = right - left
            if span <= int(min_window_ms):
                capped_minimum.append(
                    {
                        "start_ms": left,
                        "end_ms": right,
                        "rows": len(raw),
                        "cap": CAP_USERFILLS,
                    }
                )
                parsed = parser_fills(raw, vault=vault, include_raw=True)
                invalid_fill_count += len(raw) - len(parsed)
                accepted.extend(parsed)
                continue
            middle = left + max(1, span // 2)
            pending.appendleft((middle + 1, right))
            pending.appendleft((left, middle))
            splits += 1
            continue
        parsed = parser_fills(raw, vault=vault, include_raw=True)
        invalid_fill_count += len(raw) - len(parsed)
        accepted.extend(parsed)

    rows = dedupliquer(accepted)
    retention_cap_reached = len(rows) >= MAX_PUBLIC_USERFILLS
    fill_times = [
        int(row["ts_ms"])
        for row in rows
        if type(row.get("ts_ms")) is int and int(row["ts_ms"]) > 0
    ]
    return rows, {
        "status": (
            "COMPLETE"
            if not failures
            and not capped_minimum
            and not request_budget_exhausted
            and not invalid_fill_count
            and not retention_cap_reached
            else "PARTIAL"
        ),
        "requested_start_ms": int(start_ms),
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "failed_windows": failures,
        "cap_blocked_windows": capped_minimum,
        "request_budget_exhausted": request_budget_exhausted,
        "pending_windows": len(pending),
        "invalid_fill_count": invalid_fill_count,
        "retention_cap_reached": retention_cap_reached,
        "oldest_fill_ts_ms": min(fill_times) if fill_times else None,
        "newest_fill_ts_ms": max(fill_times) if fill_times else None,
        "rows": len(rows),
    }


def rest_backfill_envelopes(
    rows: list[Mapping[str, Any]],
    *,
    vault: str,
    audit: Mapping[str, Any],
    receive_wall_ms: int,
    receive_mono_ns: int,
) -> list[TickEnvelope]:
    """Preserve exact public REST fills as historical snapshots, never forward signals."""
    vault_id = str(vault or "").strip().lower()
    if not vault_id or int(receive_wall_ms) <= 0 or int(receive_mono_ns) <= 0:
        raise ValueError("historical backfill requires vault and receive clocks")
    raw_fills: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("raw_fill") if isinstance(row, Mapping) else None
        if not isinstance(raw, Mapping):
            raise ValueError("historical backfill is missing its original fill payload")
        try:
            event_ms = int(raw["time"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("historical fill is missing its exchange timestamp") from exc
        if not 0 < event_ms <= int(receive_wall_ms):
            raise ValueError("historical fill timestamp is future or invalid")
        raw_fills.append(dict(raw))

    envelopes: list[TickEnvelope] = []
    for offset in range(0, len(raw_fills), CAP_USERFILLS):
        batch = raw_fills[offset : offset + CAP_USERFILLS]
        exchange_ts_ms = max(int(fill["time"]) for fill in batch)
        envelopes.append(
            TickEnvelope(
                source_id="hyperliquid_public_userfills_backfill",
                channel="copy_vault_snapshot",
                instrument=vault_id,
                event_kind=FeedEventKind.SNAPSHOT,
                raw_payload={
                    "channel": "userFills",
                    "data": {
                        "user": vault_id,
                        "isSnapshot": True,
                        "fills": batch,
                    },
                    "backfill_audit": dict(audit),
                },
                exchange_ts_ms=exchange_ts_ms,
                received_ts_ms=int(receive_wall_ms),
                local_monotonic_ns=int(receive_mono_ns),
                connection_id=None,
                sequence=None,
                provenance={
                    "url": INFO_URL,
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": "https",
                    "authenticated": False,
                    "request_type": "userFillsByTime",
                    "forward_evidence_allowed": False,
                    "historical_only": True,
                    "timestamp_semantics": "causal_event_availability",
                },
                parsed_summary={
                    "event_count": len(batch),
                    "fill_count": len(batch),
                    "is_snapshot": True,
                    "historical_only": True,
                    "backfill_status": str(audit.get("status") or "UNAVAILABLE"),
                    "batch_index": offset // CAP_USERFILLS,
                },
            )
        )
    return envelopes


async def reconcile_forward_window(
    vaults: list[str],
    *,
    start_ms_by_vault: Mapping[str, int],
    end_ms: int,
    live_ids: Mapping[str, set[str]],
    pacer: RestWeightPacer | None = None,
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            start_ms = start_ms_by_vault.get(vault)
            if start_ms is None:
                reports[vault] = {
                    "status": "UNAVAILABLE",
                    "live_count": len(live_ids.get(vault, set())),
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": 0,
                    "live_only": len(live_ids.get(vault, set())),
                    "duplicate_live_keys": 0,
                    "audit": {
                        "status": "PARTIAL",
                        "reason": "NO_LIVE_SUBSCRIPTION_START",
                        "requested_start_ms": None,
                        "requested_end_ms": int(end_ms),
                        "rows": 0,
                    },
                }
                continue
            try:
                rows, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=int(start_ms),
                        end_ms=end_ms,
                        pacer=pacer,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                observed = set(live_ids.get(vault, set()))
                reports[vault] = {
                    "status": "UNAVAILABLE",
                    "live_count": len(observed),
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": 0,
                    "live_only": len(observed),
                    "duplicate_live_keys": 0,
                    "audit": {
                        "status": "PARTIAL",
                        "reason": "REFERENCE_TIMEOUT",
                        "timeout_s": RECONCILIATION_PER_VAULT_TIMEOUT_S,
                        "requested_start_ms": int(start_ms),
                        "requested_end_ms": int(end_ms),
                        "rows": 0,
                    },
                }
                continue
            reference_ids = {
                canonical_fill_id({**row, "vault": vault})
                for row in rows
            }
            observed = set(live_ids.get(vault, set()))
            missing = reference_ids - observed
            live_only = observed - reference_ids
            if audit["status"] != "COMPLETE":
                status = "UNAVAILABLE"
            elif missing:
                status = "MISMATCH"
            elif live_only:
                # Boundary races remain visible and cannot silently certify exactness.
                status = "PARTIAL"
            else:
                status = "MATCHED"
            reports[vault] = {
                "status": status,
                "live_count": len(observed),
                "reference_count": len(reference_ids),
                "matched_count": len(observed & reference_ids),
                "missing_from_live": len(missing),
                "live_only": len(live_only),
                "duplicate_live_keys": 0,
                "audit": audit,
            }
    return reports


async def collect_historical_backfills(
    vaults: list[str],
    *,
    selection_ts_ms: int,
    lookback_hours: float,
    history_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
    pacer: RestWeightPacer | None = None,
) -> tuple[dict[str, dict[str, Any]], list[TickEnvelope]]:
    """Capture a bounded pre-selection research window, separate from forward receipts."""
    lookback = float(lookback_hours)
    if not 0 < lookback <= MAX_HISTORY_LOOKBACK_HOURS:
        raise ValueError(
            f"history lookback must be within (0,{MAX_HISTORY_LOOKBACK_HOURS}] hours"
        )
    end_ms = int(selection_ts_ms) - 1
    default_start_ms = int(selection_ts_ms - lookback * 3_600_000)
    if default_start_ms <= 0 or end_ms < default_start_ms:
        raise ValueError("selection timestamp cannot support requested history window")

    reports: dict[str, dict[str, Any]] = {}
    envelopes: list[TickEnvelope] = []
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            vault_id = str(vault).lower()
            checkpoint = (history_checkpoints or {}).get(vault_id)
            checkpoint_end_ms = (
                checkpoint.get("last_reconciled_end_ms")
                if isinstance(checkpoint, Mapping)
                else None
            )
            if checkpoint_end_ms is None and isinstance(checkpoint, Mapping):
                checkpoint_end_ms = checkpoint.get("last_complete_end_ms")
            unresolved_gaps = (
                [dict(gap) for gap in checkpoint.get("unresolved_gaps", [])
                 if isinstance(gap, Mapping)]
                if isinstance(checkpoint, Mapping)
                and isinstance(checkpoint.get("unresolved_gaps", []), list)
                else []
            )
            start_ms = default_start_ms
            checkpoint_used = False
            checkpoint_from_future = (
                type(checkpoint_end_ms) is int and checkpoint_end_ms > end_ms
            )
            if type(checkpoint_end_ms) is int and 0 < checkpoint_end_ms <= end_ms:
                start_ms = checkpoint_end_ms
                checkpoint_used = True
            elif checkpoint_from_future:
                future_gap = {
                    "start_ms": end_ms + 1,
                    "end_ms": checkpoint_end_ms,
                    "reason": "CHECKPOINT_AFTER_SELECTION_CUTOFF",
                }
                if future_gap not in unresolved_gaps:
                    unresolved_gaps.append(future_gap)
            max_start_ms = end_ms - int(MAX_HISTORY_LOOKBACK_HOURS * 3_600_000)
            if start_ms < max_start_ms:
                gap = {
                    "start_ms": start_ms,
                    "end_ms": max_start_ms - 1,
                    "reason": "HISTORY_LOOKBACK_LIMIT_72H",
                }
                if gap not in unresolved_gaps:
                    unresolved_gaps.append(gap)
                start_ms = max_start_ms
            if start_ms <= 0 or end_ms < start_ms:
                reports[vault_id] = {
                    "status": "PARTIAL",
                    "request_audit_status": "UNAVAILABLE",
                    "reason": "INVALID_HISTORY_WINDOW",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                    "checkpoint_advance_allowed": False,
                    "unresolved_gaps": unresolved_gaps,
                    "forward_evidence_allowed": False,
                }
                continue
            try:
                rows, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        pacer=pacer,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                audit = {
                    "status": "PARTIAL",
                    "reason": "HISTORICAL_BACKFILL_TIMEOUT",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                }
                rows = []
            except Exception as exc:
                audit = {
                    "status": "PARTIAL",
                    "reason": f"HISTORICAL_BACKFILL_{type(exc).__name__}",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                }
                rows = []
            request_audit_status = str(audit.get("status") or "PARTIAL").upper()
            retention_window_reconciled = (
                audit.get("retention_cap_reached") is True
                and request_audit_status == "PARTIAL"
                and type(audit.get("rows")) is int
                and int(audit.get("rows") or 0) >= MAX_PUBLIC_USERFILLS
                and type(audit.get("oldest_fill_ts_ms")) is int
                and start_ms <= int(audit.get("oldest_fill_ts_ms") or 0) <= end_ms
                and audit.get("request_budget_exhausted") is False
                and type(audit.get("pending_windows")) is int
                and audit.get("pending_windows") == 0
                and type(audit.get("invalid_fill_count")) is int
                and audit.get("invalid_fill_count") == 0
                and audit.get("failed_windows") == []
                and audit.get("cap_blocked_windows") == []
            )
            if retention_window_reconciled:
                oldest_fill_ms = audit.get("oldest_fill_ts_ms")
                if type(oldest_fill_ms) is int and oldest_fill_ms > start_ms:
                    gap = {
                        "start_ms": start_ms,
                        "end_ms": oldest_fill_ms - 1,
                        "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT",
                    }
                    if gap not in unresolved_gaps:
                        unresolved_gaps.append(gap)
            checkpoint_advance_allowed = (
                (
                    request_audit_status == "COMPLETE"
                    and audit.get("retention_cap_reached") is False
                )
                or retention_window_reconciled
            ) and (
                not checkpoint_from_future
                and audit.get("request_budget_exhausted") is False
                and type(audit.get("pending_windows")) is int
                and audit.get("pending_windows") == 0
                and type(audit.get("invalid_fill_count")) is int
                and audit.get("invalid_fill_count") == 0
                and audit.get("failed_windows") == []
                and audit.get("cap_blocked_windows") == []
            )
            report_status = (
                "COMPLETE"
                if request_audit_status == "COMPLETE" and not unresolved_gaps
                else "PARTIAL"
            )
            report = {
                **dict(audit),
                "status": report_status,
                "request_audit_status": request_audit_status,
                "vault": vault_id,
                "window_kind": (
                    "CONTINUITY_RECONCILIATION"
                    if checkpoint_used
                    else "PRE_SELECTION_HISTORICAL_RESEARCH_ONLY"
                ),
                "lookback_hours": lookback,
                "checkpoint_start_ms": checkpoint_end_ms if checkpoint_used else None,
                "checkpoint_advance_allowed": checkpoint_advance_allowed,
                "unresolved_gaps": unresolved_gaps,
                "forward_evidence_allowed": False,
            }
            accounting_backfills: dict[str, dict[str, Any]] = {}
            for request_type, family in (
                ("userFunding", "copy_vault_funding"),
                ("userNonFundingLedgerUpdates", "copy_vault_ledger"),
            ):
                try:
                    account_rows, account_audit = await asyncio.wait_for(
                        exact_window_accounting_backfill(
                            client,
                            vault,
                            request_type=request_type,
                            start_ms=default_start_ms,
                            end_ms=end_ms,
                            pacer=pacer,
                        ),
                        timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                    )
                except TimeoutError:
                    account_rows = []
                    account_audit = {
                        "request_type": request_type,
                        "status": "PARTIAL",
                        "requested_start_ms": default_start_ms,
                        "requested_end_ms": end_ms,
                        "reason": "ACCOUNTING_BACKFILL_TIMEOUT",
                        "event_count": 0,
                        "proof_of_pnl_allowed": False,
                        "forward_evidence_allowed": False,
                    }
                except Exception as exc:
                    account_rows = []
                    account_audit = {
                        "request_type": request_type,
                        "status": "PARTIAL",
                        "requested_start_ms": default_start_ms,
                        "requested_end_ms": end_ms,
                        "reason": f"ACCOUNTING_BACKFILL_{type(exc).__name__}",
                        "event_count": 0,
                        "proof_of_pnl_allowed": False,
                        "forward_evidence_allowed": False,
                    }
                account_audit = {**dict(account_audit), "vault": vault_id}
                accounting_backfills[family] = account_audit
                if account_rows:
                    receive_wall_ms = int(time.time() * 1_000)
                    receive_mono_ns = time.monotonic_ns()
                    envelopes.extend(
                        rest_accounting_backfill_envelopes(
                            account_rows,
                            vault=vault,
                            request_type=request_type,
                            audit=account_audit,
                            receive_wall_ms=receive_wall_ms,
                            receive_mono_ns=receive_mono_ns,
                        )
                    )
            report["accounting_backfill"] = accounting_backfills
            report["accounting_history_start_ms"] = default_start_ms
            report["accounting_history_end_ms"] = end_ms
            report["accounting_history_forward_evidence_allowed"] = False
            reports[vault_id] = report
            if rows:
                receive_wall_ms = int(time.time() * 1_000)
                receive_mono_ns = time.monotonic_ns()
                envelopes.extend(
                    rest_backfill_envelopes(
                        rows,
                        vault=vault,
                        audit=report,
                        receive_wall_ms=receive_wall_ms,
                        receive_mono_ns=receive_mono_ns,
                    )
                )
    return reports, envelopes


def build_copy_vault_bundle(
    raw_root: Path,
    output: Path,
    *,
    collector_version: str,
    reconciliation: Mapping[str, Mapping[str, Any]],
    queue_drops: Mapping[tuple[str, str, str], int],
    selection: Mapping[str, Any],
    collection_run_id: str,
    historical_backfill: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    assets = output / "assets"
    manifests_dir = output / "manifests"
    assets.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict[str, Any]] = []
    rejected_admission: list[dict[str, Any]] = []
    for shard in sorted(raw_root.glob("**/shards/*.jsonl.gz")):
        preliminary = build_manifest_from_tick_shard(
            shard,
            collector_version=collector_version,
            reconciliation_status="UNVERIFIED",
        )
        vault = str(preliminary.get("symbol") or "").lower()
        family = str(preliminary.get("family") or "")
        report = reconciliation.get(vault, {})
        if family == "copy_vault_fills":
            preliminary["reconciliation"] = {
                "status": str(report.get("status") or "UNVERIFIED").upper(),
                "live_count": report.get("live_count"),
                "reference_count": report.get("reference_count"),
                "matched_count": report.get("matched_count"),
                "missing_from_live": report.get("missing_from_live"),
                "live_only": report.get("live_only"),
                "audit": dict(report.get("audit") or {}),
            }
        elif family == "copy_vault_snapshot":
            source_id = str(preliminary.get("source") or "")
            history_report = (historical_backfill or {}).get(vault, {})
            if source_id == "hyperliquid_public_userfills_backfill":
                audit = dict(history_report)
                status = (
                    "SNAPSHOT_VERIFIED"
                    if str(audit.get("status") or "").upper() == "COMPLETE"
                    else "UNAVAILABLE"
                )
                preliminary["copy_vault_history"] = audit
                preliminary["reconciliation"] = {
                    "status": status,
                    "method": "bounded_userFillsByTime_pre_selection_v1",
                    "forward_evidence_allowed": False,
                }
            else:
                preliminary["reconciliation"] = {
                    "status": infer_reconciliation_status(preliminary),
                    "method": "websocket_userFills_bootstrap_snapshot_v1",
                    "forward_evidence_allowed": False,
                }
        elif family in {"copy_vault_positions", "copy_vault_selection"}:
            # Immutable public HTTP observation, not an exchange-timestamped
            # trade. Verify local causality and explicit receive-only semantics.
            preliminary["reconciliation"] = {
                "status": infer_reconciliation_status(preliminary),
                "method": "observed_public_http_state_v1",
            }
        elif family in {"copy_vault_funding", "copy_vault_ledger"}:
            history_report = (historical_backfill or {}).get(vault, {})
            accounting_report = (
                history_report.get("accounting_backfill", {}).get(family, {})
                if isinstance(history_report, Mapping)
                and isinstance(history_report.get("accounting_backfill"), Mapping)
                else {}
            )
            preliminary["copy_vault_accounting_history"] = dict(accounting_report)
            preliminary["reconciliation"] = {
                "status": infer_reconciliation_status(preliminary),
                "method": "public_account_event_capture_v2",
                "history_status": str(accounting_report.get("status") or "UNAVAILABLE"),
                "proof_of_pnl_allowed": False,
                "forward_evidence_allowed": False,
            }
        else:
            preliminary["reconciliation"] = {"status": "UNVERIFIED"}

        key = (
            str(preliminary["source"]),
            family,
            str(preliminary["symbol"]),
        )
        dropped = int(queue_drops.get(key, 0))
        if dropped:
            integrity = dict(preliminary.get("integrity") or {})
            integrity["gap_count"] = int(integrity.get("gap_count") or 0) + dropped
            preliminary["integrity"] = integrity
            preliminary["collection_queue_drops"] = dropped
        preliminary["collection_run_id"] = str(collection_run_id)
        historical_only = (
            family == "copy_vault_snapshot"
            or str(preliminary.get("source") or "")
            == "hl_public_account_backfill"
        )
        preliminary["copy_vault_selection"] = {
            "selected_at_ms": selection.get("selected_at_ms"),
            "observation_only": True,
            "forward_only": not historical_only,
            "historical_only": historical_only,
        }
        manifest = finalize_manifest(preliminary)
        if not locally_replay_admissible(manifest):
            rejected_admission.append(admission_rejection(manifest))
            # No unreplayable market payload or trade enters the publish bundle.
            continue

        asset_name = f"{manifest['dataset_id']}.jsonl.gz"
        target = assets / asset_name
        shutil.move(str(shard), target)
        manifest["release_asset"] = asset_name
        manifest["bytes"] = target.stat().st_size
        write_manifest(manifest, manifests_dir / f"{manifest['dataset_id']}.json")
        manifests.append(manifest)

    index = {
        "schema": V2_SCHEMA,
        "repository": V2_REPOSITORY,
        "collector_version": collector_version,
        "collection_run_id": str(collection_run_id),
        "collection_kind": (
            "copy_vault_forward_plus_historical_research"
            if historical_backfill is not None
            else "copy_vault_forward"
        ),
        "selection": dict(selection),
        "historical_backfill": {
            str(vault): dict(report)
            for vault, report in (historical_backfill or {}).items()
        },
        "collection_queue_drops": sum(int(v) for v in queue_drops.values()),
        "source_admission": {
            "mode": "replay_only",
            **summarize_admission_rejections(rejected_admission),
        },
        "shard_count": len(manifests),
        "safe_count": sum(1 for row in manifests if row["quality_status"] == "SAFE"),
        "partial_count": sum(1 for row in manifests if row["quality_status"] == "PARTIAL"),
        "reject_count": sum(1 for row in manifests if row["quality_status"] == "REJECT"),
        "dataset_ids": [row["dataset_id"] for row in manifests],
        "manifests": [f"manifests/{row['dataset_id']}.json" for row in manifests],
        "assets": [f"assets/{row['release_asset']}" for row in manifests],
        "read_only": True,
        "real_execution": False,
    }
    write_manifest(index, output / "BUNDLE_INDEX.json")
    return index


async def collect(
    output: Path,
    *,
    duration_s: float,
    collector_version: str,
    max_vaults: int,
    vault_shard_count: int = 1,
    vault_shard_index: int = 0,
    max_ws_vaults: int = MAX_PRIORITY_WS_VAULTS,
    two_speed: bool = False,
    rotate_bytes: int,
    collection_run_id: str | None = None,
    frozen_selection: Mapping[str, Any] | None = None,
    history_lookback_hours: float = DEFAULT_HISTORY_LOOKBACK_HOURS,
) -> dict[str, Any]:
    if not 0 < float(history_lookback_hours) <= MAX_HISTORY_LOOKBACK_HOURS:
        raise ValueError(
            f"history lookback must be within (0,{MAX_HISTORY_LOOKBACK_HOURS}] hours"
        )
    if frozen_selection is None:
        selected_rows, selection = await asyncio.to_thread(
            discover_vaults,
            max_vaults=max_vaults,
        )
    else:
        selection = dict(frozen_selection)
        raw_rows = selection.get("vaults")
        if not isinstance(raw_rows, list):
            raise ValueError("frozen selection must contain a vaults list")
        selected_rows = [
            dict(row)
            for row in raw_rows
            if isinstance(row, Mapping) and str(row.get("address") or "").strip()
        ][: max(1, int(max_vaults))]
        if not selected_rows:
            raise ValueError("frozen selection contains no usable vaults")

    history_checkpoints_by_vault = {
        str(row.get("address") or "").lower(): row["copy_vault_history_checkpoint"]
        for row in selected_rows
        if isinstance(row.get("copy_vault_history_checkpoint"), Mapping)
    }

    shard_count = max(1, int(vault_shard_count))
    shard_index = int(vault_shard_index)
    if not 0 <= shard_index < shard_count:
        raise ValueError("vault_shard_index must be within vault_shard_count")
    full_count = len(selected_rows)
    if two_speed and (shard_count != 1 or shard_index != 0):
        raise ValueError("two-speed Copy-Vault collection requires one broad universe lane")

    selection_ts_ms = int(selection["selected_at_ms"])
    run_id = str(collection_run_id or "").strip() or (
        f"copy-vault-{str(collector_version)[:12]}-{selection_ts_ms}-"
        f"s{shard_index}of{shard_count}"
    )
    rest_pacer = RestWeightPacer()

    raw_root = output / "raw"
    writer = PartitionedTickDatasetWriter(
        raw_root,
        rotate_bytes=rotate_bytes,
        flush_every=1,
    )
    sink = AsyncTickSink(writer)
    writer_task = asyncio.create_task(sink.run())

    broad_start: dict[str, Any] = {}
    broad_end: dict[str, Any] = {}
    changed_fingerprints = 0

    if two_speed:
        universe_rows = list(selected_rows)
        broad_start = await collect_broad_state(
            universe_rows,
            sink,
            phase="START",
            pacer=rest_pacer,
        )
        priority_rows = select_priority_ws_vaults(
            universe_rows,
            broad_start,
            max_ws_vaults=max_ws_vaults,
            rotation_seed=run_id,
        )
        selected_rows = priority_rows
        broad_digest = hashlib.sha256(
            "\n".join(
                sorted(str(row.get("address") or "").lower() for row in universe_rows)
            ).encode("utf-8")
        ).hexdigest()
        selection = {
            **selection,
            "mode": "two_speed_broad_rest_priority_ws",
            "full_vault_count": full_count,
            "broad_vault_count": full_count,
            "broad_selection_digest": broad_digest,
            "vault_count": len(priority_rows),
            "max_ws_vaults": min(MAX_PRIORITY_WS_VAULTS, int(max_ws_vaults)),
            "vault_shard_count": 1,
            "vault_shard_index": 0,
            "vaults": priority_rows,
        }
    else:
        selected_rows = selected_rows[shard_index::shard_count]
        selection = {
            **selection,
            "mode": "legacy_sharded_ws",
            "full_vault_count": full_count,
            "vault_count": len(selected_rows),
            "vault_shard_count": shard_count,
            "vault_shard_index": shard_index,
            "vaults": selected_rows,
        }

    vaults = [str(row["address"]).lower() for row in selected_rows]
    if not vaults:
        raise RuntimeError("selected Copy-Vault lane is empty")
    validate_user_subscription_budget(vaults)

    for row in selected_rows:
        await _emit_with_backpressure(sink, selection_envelope(row, selection))

    live_ids: dict[str, set[str]] = defaultdict(set)
    live_fill_counts: dict[str, int] = defaultdict(int)
    unclassified_fill_counts: dict[str, int] = defaultdict(int)
    observation_start_ms: dict[str, int] = {}
    reconnect_counts: dict[str, int] = defaultdict(int)
    subscription_attempts: dict[str, list[dict[str, Any]]] = {}
    subscription_attempts_dropped: dict[str, int] = {}
    subscription_diagnostics: dict[str, int] = {}
    snapshot_fill_ids: dict[str, set[str]] = defaultdict(set)
    l2_request_queue: asyncio.Queue[str] = asyncio.Queue()
    l2_known_coins: set[str] = set()
    l2_state = new_l2_state()
    position_snapshots_start = await collect_position_snapshots(
        vaults,
        sink,
        phase="START",
        pacer=rest_pacer,
    )

    collection_launch_ms = int(time.time() * 1_000)
    groups = [
        vaults[index:index + MAX_SUBSCRIPTIONS_PER_SOCKET]
        for index in range(0, len(vaults), MAX_SUBSCRIPTIONS_PER_SOCKET)
    ]
    tasks = [
        asyncio.create_task(
            _socket_group(
                group,
                sink,
                observation_start_ms=observation_start_ms,
                live_ids=live_ids,
                live_fill_counts=live_fill_counts,
                unclassified_fill_counts=unclassified_fill_counts,
                reconnect_counts=reconnect_counts,
                l2_request_queue=l2_request_queue,
                l2_known_coins=l2_known_coins,
                subscription_attempts=subscription_attempts,
                subscription_attempts_dropped=subscription_attempts_dropped,
                subscription_diagnostics=subscription_diagnostics,
                snapshot_fill_ids=snapshot_fill_ids,
            )
        )
        for group in groups
    ]
    tasks.append(
        asyncio.create_task(
            _dynamic_l2_collector(
                sink,
                l2_request_queue,
                l2_known_coins,
                l2_state,
            )
        )
    )

    requested_duration = max(1.0, float(duration_s))
    if two_speed:
        estimated_end_sweep_s = (
            float(full_count) * BROAD_SWEEP_REQUEST_INTERVAL_S * 1.10
        )
        ws_duration_s = max(
            60.0,
            requested_duration
            - float(broad_start.get("elapsed_s") or 0.0)
            - estimated_end_sweep_s,
        )
    else:
        ws_duration_s = requested_duration

    try:
        await asyncio.sleep(ws_duration_s)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    position_snapshots_end = await collect_position_snapshots(
        vaults,
        sink,
        phase="END",
        pacer=rest_pacer,
    )

    if two_speed:
        broad_end = await collect_broad_state(
            universe_rows,
            sink,
            phase="END",
            pacer=rest_pacer,
        )
        start_states = broad_start.get("states")
        end_states = broad_end.get("states")
        if isinstance(start_states, Mapping) and isinstance(end_states, Mapping):
            changed_fingerprints = sum(
                1
                for address in set(start_states) & set(end_states)
                if str(start_states[address].get("position_fingerprint") or "")
                != str(end_states[address].get("position_fingerprint") or "")
            )

    end_ms = int(time.time() * 1_000)
    reports = await reconcile_forward_window(
        vaults,
        start_ms_by_vault=observation_start_ms,
        end_ms=end_ms,
        live_ids=live_ids,
        pacer=rest_pacer,
    )
    historical_reports, historical_envelopes = await collect_historical_backfills(
        vaults,
        selection_ts_ms=selection_ts_ms,
        lookback_hours=history_lookback_hours,
        history_checkpoints=history_checkpoints_by_vault,
        pacer=rest_pacer,
    )
    for envelope in historical_envelopes:
        await _emit_with_backpressure(sink, envelope)
    await sink.close()
    await writer_task
    await asyncio.to_thread(writer.rotate_all)

    index = await asyncio.to_thread(
        build_copy_vault_bundle,
        raw_root,
        output,
        collector_version=collector_version,
        reconciliation=reports,
        queue_drops=sink.drops,
        selection=selection,
        collection_run_id=run_id,
        historical_backfill=historical_reports,
    )
    effective_start_ms = min(
        observation_start_ms.values(),
        default=collection_launch_ms,
    )
    summary = {
        "schema": "alina.copy_vault_cloud_window.v2",
        "collection_run_id": run_id,
        "selection_ts_ms": selection_ts_ms,
        "collection_launch_ts_ms": collection_launch_ms,
        "collection_start_ts_ms": effective_start_ms,
        "vault_observation_start_ts_ms": dict(sorted(observation_start_ms.items())),
        "end_ts_ms": end_ms,
        "duration_s": round((end_ms - effective_start_ms) / 1000.0, 3),
        "requested_duration_s": requested_duration,
        "ws_duration_s": round(ws_duration_s, 3),
        "vault_count": len(vaults),
        "vault_universe_count": selection.get("full_vault_count"),
        "vault_shard_count": selection.get("vault_shard_count"),
        "vault_shard_index": selection.get("vault_shard_index"),
        "copy_vault_mode": selection.get("mode"),
        "priority_ws_vaults": vaults,
        "socket_groups": len(groups),
        "vault_subscription_attempts": _public_subscription_attempts(
            subscription_attempts
        ),
        "vault_subscription_attempts_dropped": dict(
            sorted(subscription_attempts_dropped.items())
        ),
        "subscription_diagnostics": dict(sorted(subscription_diagnostics.items())),
        "l2_coin_count": len(l2_known_coins),
        "l2_frames": l2_state.get("frames", 0),
        "l2_reconnects": l2_state.get("reconnects", 0),
        "l2_heartbeats": l2_state.get("heartbeats", 0),
        "l2_diagnostics": _l2_diagnostics(
            l2_state,
            end_ms=end_ms,
            requested_coins=l2_known_coins,
        ),
        "position_snapshots_start": position_snapshots_start,
        "position_snapshots_end": position_snapshots_end,
        "broad_sweep_start": _compact_sweep_metrics(broad_start),
        "broad_sweep_end": _compact_sweep_metrics(broad_end),
        "broad_position_fingerprints_changed": changed_fingerprints,
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "backpressure_events": sink.backpressure_events,
        "queue_drops": sum(int(v) for v in sink.drops.values()),
        "live_fill_counts": dict(sorted(live_fill_counts.items())),
        "unclassified_userfills_fill_counts": dict(sorted(unclassified_fill_counts.items())),
        "reconnect_counts": dict(sorted(reconnect_counts.items())),
        "reconciliation": reports,
        "historical_backfill": historical_reports,
        "historical_unique_fill_rows": sum(
            int(report.get("rows") or 0)
            for report in historical_reports.values()
        ),
        "historical_backfill_complete_vaults": sum(
            str(report.get("status") or "").upper() == "COMPLETE"
            for report in historical_reports.values()
        ),
        "history_lookback_hours": float(history_lookback_hours),
        "rest_weight_budget_per_minute": REST_WEIGHT_BUDGET_PER_MINUTE,
        "bundle": {
            "shard_count": index["shard_count"],
            "safe_count": index["safe_count"],
            "partial_count": index["partial_count"],
            "reject_count": index["reject_count"],
        },
        "read_only": True,
        "real_execution": False,
    }
    (output / "collection_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--collection-run-id")
    parser.add_argument("--selection-file")
    parser.add_argument("--max-vaults", type=int, default=100)
    parser.add_argument("--vault-shard-count", type=int, default=1)
    parser.add_argument("--vault-shard-index", type=int, default=0)
    parser.add_argument("--max-ws-vaults", type=int, default=MAX_PRIORITY_WS_VAULTS)
    parser.add_argument("--two-speed", action="store_true")
    parser.add_argument(
        "--history-lookback-hours",
        type=float,
        default=DEFAULT_HISTORY_LOOKBACK_HOURS,
    )
    parser.add_argument("--rotate-mb", type=int, default=64)
    args = parser.parse_args()
    frozen_selection = None
    if args.selection_file:
        payload = json.loads(Path(args.selection_file).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise SystemExit("selection file must contain a JSON object")
        frozen_selection = payload

    summary = asyncio.run(
        collect(
            Path(args.output),
            duration_s=max(1.0, float(args.duration_s)),
            collector_version=str(args.collector_version),
            max_vaults=max(1, int(args.max_vaults)),
            vault_shard_count=max(1, int(args.vault_shard_count)),
            vault_shard_index=int(args.vault_shard_index),
            max_ws_vaults=max(1, min(MAX_PRIORITY_WS_VAULTS, int(args.max_ws_vaults))),
            two_speed=bool(args.two_speed),
            rotate_bytes=max(1, int(args.rotate_mb)) * 1024 * 1024,
            collection_run_id=args.collection_run_id,
            frozen_selection=frozen_selection,
            history_lookback_hours=float(args.history_lookback_hours),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
