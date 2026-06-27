from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from hl_observer.collection.backoff import BackoffPolicy, compute_backoff_delay
from hl_observer.sources.collection_recorder import CollectionRecorder


WS_MAX_UNIQUE_USERS = 10
WS_MAX_SUBSCRIPTIONS = 1000
WS_MAX_MESSAGES_PER_MINUTE = 2000
WS_MAX_NEW_CONNECTIONS_PER_MINUTE = 30


@dataclass(frozen=True, slots=True)
class WsSubscriptionPlan:
    allowed: bool
    unique_user_count: int
    subscription_count: int
    refusal_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    execution: str = "forbidden"
    fallback_to_rest: bool = False


@dataclass(frozen=True, slots=True)
class WsMessageDecision:
    accepted: bool
    event_key: str
    is_snapshot: bool
    reason: str
    needs_gap_recovery: bool = False


@dataclass(slots=True)
class WsSupervisor:
    heartbeat_max_age_ms: int = 30_000
    backoff_policy: BackoffPolicy = field(default_factory=BackoffPolicy)
    recorder: CollectionRecorder | None = None
    reconnect_attempt: int = 0
    last_heartbeat_ms: int | None = None
    accepted_events: int = 0
    duplicate_events: int = 0
    _seen_keys: set[str] = field(default_factory=set)
    _seen_snapshot_items: set[str] = field(default_factory=set)

    def plan_subscriptions(
        self,
        wallets: list[str] | tuple[str, ...],
        market_channels: int = 0,
        *,
        messages_per_minute: int = 0,
        new_connections_per_minute: int = 1,
    ) -> WsSubscriptionPlan:
        unique_wallets = tuple(dict.fromkeys(str(wallet).lower() for wallet in wallets if str(wallet).strip()))
        subscription_count = len(unique_wallets) + max(0, int(market_channels))
        reasons: list[str] = []
        warnings: list[str] = []
        if len(unique_wallets) > WS_MAX_UNIQUE_USERS:
            reasons.append("WS_UNIQUE_USER_CAP_EXCEEDED")
        if subscription_count > WS_MAX_SUBSCRIPTIONS:
            reasons.append("WS_SUBSCRIPTION_CAP_EXCEEDED")
        if messages_per_minute > WS_MAX_MESSAGES_PER_MINUTE:
            reasons.append("WS_MESSAGES_PER_MINUTE_CAP_EXCEEDED")
        if new_connections_per_minute > WS_MAX_NEW_CONNECTIONS_PER_MINUTE:
            reasons.append("WS_NEW_CONNECTIONS_PER_MINUTE_CAP_EXCEEDED")
        if len(unique_wallets) == WS_MAX_UNIQUE_USERS:
            warnings.append("WS_USER_CAP_REACHED")
        if subscription_count >= int(WS_MAX_SUBSCRIPTIONS * 0.8):
            warnings.append("WS_SUBSCRIPTION_CAP_NEAR")
        return WsSubscriptionPlan(
            allowed=not reasons,
            unique_user_count=len(unique_wallets),
            subscription_count=subscription_count,
            refusal_reasons=tuple(reasons),
            warnings=tuple(warnings),
            fallback_to_rest=bool(reasons),
        )

    def accept_message(self, message: dict[str, Any], *, received_at_ms: int) -> WsMessageDecision:
        key = _event_key(message)
        is_snapshot = bool(_data(message).get("isSnapshot"))
        channel = str(message.get("channel") or _data(message).get("channel") or "unknown")
        self._record_message(channel=channel, message=message, received_at_ms=received_at_ms)
        if is_snapshot:
            snapshot_items = _snapshot_item_keys(message)
            if snapshot_items:
                new_items = snapshot_items - self._seen_snapshot_items
                if not new_items:
                    self.duplicate_events += 1
                    return WsMessageDecision(False, key, True, "DUPLICATE_WS_SNAPSHOT")
                self._seen_snapshot_items.update(new_items)
        if key in self._seen_keys:
            self.duplicate_events += 1
            return WsMessageDecision(False, key, is_snapshot, "DUPLICATE_WS_EVENT")
        self._seen_keys.add(key)
        self.accepted_events += 1
        self.last_heartbeat_ms = received_at_ms
        self.reconnect_attempt = 0
        return WsMessageDecision(True, key, is_snapshot, "ACCEPTED")

    def heartbeat_stale(self, *, now_ms: int) -> bool:
        if self.last_heartbeat_ms is None:
            return True
        return now_ms - self.last_heartbeat_ms > self.heartbeat_max_age_ms

    def next_reconnect_delay(self) -> float:
        decision = compute_backoff_delay(
            attempt=self.reconnect_attempt,
            policy=self.backoff_policy,
            status_code=None,
            shard_key="ws",
        )
        self.reconnect_attempt += 1
        return decision.delay_seconds

    def gap_recovery_decision(self, *, now_ms: int) -> WsMessageDecision:
        if self.heartbeat_stale(now_ms=now_ms):
            return WsMessageDecision(
                accepted=False,
                event_key=f"gap:{now_ms}",
                is_snapshot=False,
                reason="HEARTBEAT_STALE_REST_GAP_RECOVERY",
                needs_gap_recovery=True,
            )
        return WsMessageDecision(False, f"gap:{now_ms}", False, "NO_GAP_RECOVERY_NEEDED")

    def source_health_summary(self, *, now_ms: int) -> dict[str, object]:
        if self.recorder is None:
            return {
                "sources": 0,
                "by_status": {},
                "usable": 0,
                "raw_events_stored": 0,
                "ws_recorder": "disabled",
            }
        summary = self.recorder.summary(now_ms=now_ms)
        return {**summary, "ws_recorder": "enabled"}

    def _record_message(self, *, channel: str, message: dict[str, Any], received_at_ms: int) -> None:
        if self.recorder is None:
            return
        self.recorder.record_ws(channel=channel, message=message, ok=True, now_ms=received_at_ms)


def _event_key(message: dict[str, Any]) -> str:
    data = _data(message)
    channel = str(message.get("channel") or data.get("channel") or "unknown")
    if bool(data.get("isSnapshot")):
        fills = data.get("fills")
        if isinstance(fills, list):
            item_keys = []
            for item in fills:
                if isinstance(item, dict):
                    item_keys.append(str(item.get("hash") or item.get("tid") or item.get("oid") or item))
                else:
                    item_keys.append(str(item))
            return f"{channel}:snapshot:" + sha256("|".join(sorted(item_keys)).encode("utf-8")).hexdigest()
    return f"{channel}:event:" + sha256(json.dumps(message, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _snapshot_item_keys(message: dict[str, Any]) -> set[str]:
    data = _data(message)
    channel = str(message.get("channel") or data.get("channel") or "unknown")
    keys: set[str] = set()
    for field_name in ("fills", "orders", "trades", "events"):
        items = data.get(field_name)
        if not isinstance(items, list):
            continue
        for item in items:
            keys.add(f"{channel}:{field_name}:{_item_key(item)}")
    return keys


def _item_key(item: Any) -> str:
    if isinstance(item, dict):
        for field_name in ("hash", "tid", "oid", "cloid", "time"):
            value = item.get(field_name)
            if value not in (None, ""):
                return str(value)
    return sha256(json.dumps(item, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _data(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data", {})
    return data if isinstance(data, dict) else {}
