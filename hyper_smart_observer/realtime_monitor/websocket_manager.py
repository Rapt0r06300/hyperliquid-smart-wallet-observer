from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.pipeline.source_health import SourceHealth, build_source_health
from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe
from hyper_smart_observer.realtime_monitor.event_router import EventRouter
from hyper_smart_observer.realtime_monitor.heartbeat import (
    HEARTBEAT_INTERVAL_SECONDS,
    build_heartbeat_payload,
)
from hyper_smart_observer.realtime_monitor.reconnect import backoff_seconds
from hyper_smart_observer.realtime_monitor.stream_models import StreamEvent, StreamType, now_event
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription, SubscriptionPlanner


_ALLOWED_OUTBOUND_METHODS = {"subscribe", "unsubscribe", "ping"}
_CONTROL_CHANNELS = {"subscriptionResponse", "pong"}


@dataclass(frozen=True)
class MonitorPlan:
    dry_run: bool
    duration_seconds: int | None
    subscriptions: list[Subscription]
    read_only: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebSocketQaReport:
    read_only: bool
    bounded_duration: bool
    duration_seconds: int | None
    subscription_count: int
    unique_user_count: int
    fallback_to_rest_polling: bool
    stopped_reason: str
    warnings: list[str] = field(default_factory=list)
    source_health: list[SourceHealth] = field(default_factory=list)


@dataclass(frozen=True)
class WebSocketRunReport:
    read_only: bool
    bounded_duration: bool
    duration_seconds: int
    subscription_count: int
    unique_user_count: int
    connected_sessions: int
    reconnect_count: int
    messages_received: int
    events_routed: int
    snapshot_messages: int
    duplicate_messages: int
    heartbeat_count: int
    fallback_to_rest_polling: bool
    stopped_reason: str
    warnings: list[str] = field(default_factory=list)
    source_health: list[SourceHealth] = field(default_factory=list)


class WebSocketManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.planner = SubscriptionPlanner(config)

    def build_plan(
        self,
        subscriptions: list[Subscription],
        *,
        dry_run: bool = True,
        duration_seconds: int | None = 60,
    ) -> MonitorPlan:
        warnings: list[str] = []
        if not dry_run and (duration_seconds is None or duration_seconds <= 0):
            warnings.append("Realtime monitor requires a bounded duration.")
        if not self.config.ws_monitor_enabled and not dry_run:
            warnings.append("WebSocket monitor is disabled by default.")
        if not self.config.enable_network_reads and not dry_run:
            warnings.append("Network reads are disabled by default.")
        try:
            accepted = self.planner.validate(subscriptions)
        except ValueError as exc:
            accepted = []
            warnings.append(str(exc))
        return MonitorPlan(
            dry_run=dry_run,
            duration_seconds=duration_seconds,
            subscriptions=accepted,
            warnings=warnings,
        )

    def qa_readiness(
        self,
        subscriptions: list[Subscription],
        *,
        dry_run: bool = True,
        duration_seconds: int | None = 60,
    ) -> WebSocketQaReport:
        """Retourne la preuve de préparation sans ouvrir de socket."""

        plan = self.build_plan(subscriptions, dry_run=dry_run, duration_seconds=duration_seconds)
        bounded = duration_seconds is not None and duration_seconds > 0
        unique_users = {(sub.user or "").lower() for sub in plan.subscriptions if sub.user}
        fallback = bool(plan.warnings) or not plan.subscriptions or not bounded
        if not plan.subscriptions:
            stopped_reason = "no_subscriptions_fallback_rest_polling"
        elif not bounded:
            stopped_reason = "unbounded_duration_fallback_rest_polling"
        elif plan.warnings:
            stopped_reason = "ws_plan_warning_fallback_rest_polling"
        else:
            stopped_reason = "bounded_read_only_ws_ready"
        health = build_source_health(
            "ws.shortlist",
            ok=not fallback,
            degraded_reason="; ".join(plan.warnings) if plan.warnings else ("fallback_rest_polling" if fallback else None),
            raw_ref=stopped_reason,
        )
        return WebSocketQaReport(
            read_only=True,
            bounded_duration=bounded,
            duration_seconds=duration_seconds,
            subscription_count=len(plan.subscriptions),
            unique_user_count=len(unique_users),
            fallback_to_rest_polling=fallback,
            stopped_reason=stopped_reason,
            warnings=list(plan.warnings),
            source_health=[health],
        )

    def run_bounded(
        self,
        subscriptions: list[Subscription],
        *,
        duration_seconds: int,
        connector: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        heartbeat_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        receive_timeout_seconds: float = 1.0,
        max_events: int = 10_000,
        max_reconnects: int = 5,
    ) -> WebSocketRunReport:
        """Exécute une session WS read-only, bornée et reconnectable.

        Le transport sortant est volontairement réduit à ``subscribe``,
        ``unsubscribe`` et ``ping``. La méthode WebSocket ``post`` n'est jamais
        autorisée, même pour une requête ``info``, afin qu'aucun futur appel ne
        puisse dériver vers une action signée sur ce chemin de recherche.
        """

        if duration_seconds <= 0:
            return self._run_refusal(subscriptions, duration_seconds, "unbounded_duration_fallback_rest_polling")
        if max_events <= 0:
            return self._run_refusal(subscriptions, duration_seconds, "invalid_max_events_fallback_rest_polling")

        plan = self.build_plan(subscriptions, dry_run=False, duration_seconds=duration_seconds)
        if plan.warnings or not plan.subscriptions:
            reason = "ws_plan_warning_fallback_rest_polling" if plan.warnings else "no_subscriptions_fallback_rest_polling"
            return self._run_refusal(plan.subscriptions, duration_seconds, reason, plan.warnings)

        connect = connector or _default_connector
        deadline = clock() + float(duration_seconds)
        router = EventRouter()
        message_dedupe = EventDedupe(max_keys=max(10_000, max_events * 2))
        warnings: list[str] = []
        connected_sessions = 0
        reconnect_count = 0
        messages_received = 0
        snapshot_messages = 0
        duplicate_messages = 0
        heartbeat_count = 0
        stopped_reason = "duration_elapsed"

        while clock() < deadline and len(router.events) < max_events:
            sock = None
            try:
                sock = connect(self.config.hyperliquid_ws_base_url, timeout=receive_timeout_seconds)
                connected_sessions += 1
                if hasattr(sock, "settimeout"):
                    sock.settimeout(receive_timeout_seconds)
                for subscription in plan.subscriptions:
                    _safe_send(sock, _subscribe_payload(subscription))
                last_heartbeat = clock()

                while clock() < deadline and len(router.events) < max_events:
                    now = clock()
                    if heartbeat_seconds > 0 and now - last_heartbeat >= heartbeat_seconds:
                        _safe_send(sock, build_heartbeat_payload())
                        heartbeat_count += 1
                        last_heartbeat = now
                    try:
                        raw = sock.recv()
                    except Exception as exc:  # websocket-client + fakes de tests
                        if _is_timeout(exc):
                            continue
                        raise
                    if raw is None:
                        raise ConnectionError("WebSocket fermé par le serveur.")
                    message = _decode_message(raw)
                    if message is None:
                        warnings.append("ws_message_invalid_json")
                        continue
                    messages_received += 1
                    channel = str(message.get("channel") or message.get("type") or "")
                    if channel in _CONTROL_CHANNELS:
                        continue
                    if channel == "post" or str(message.get("method") or "") == "post":
                        warnings.append("ws_post_channel_ignored")
                        continue
                    event = _message_to_event(message)
                    if event is None:
                        warnings.append(f"ws_unknown_channel:{channel or 'missing'}")
                        continue
                    is_snapshot = event.is_snapshot
                    if not message_dedupe.accept_hyperliquid_message(message):
                        duplicate_messages += 1
                        continue
                    if is_snapshot:
                        snapshot_messages += 1
                    router.route(event)
            except Exception as exc:
                reconnect_count += 1
                warnings.append(f"ws_disconnect:{type(exc).__name__}")
                if reconnect_count > max_reconnects:
                    stopped_reason = "reconnect_budget_exhausted_fallback_rest_polling"
                    break
                remaining = max(0.0, deadline - clock())
                if remaining <= 0:
                    break
                sleeper(min(backoff_seconds(reconnect_count), remaining))
            finally:
                if sock is not None:
                    try:
                        for subscription in plan.subscriptions:
                            _safe_send(sock, _unsubscribe_payload(subscription))
                    except Exception:
                        pass
                    try:
                        sock.close()
                    except Exception:
                        pass

        if len(router.events) >= max_events:
            stopped_reason = "max_events_reached"
        elif clock() >= deadline and stopped_reason == "duration_elapsed":
            stopped_reason = "duration_elapsed"
        fallback = connected_sessions == 0 or stopped_reason == "reconnect_budget_exhausted_fallback_rest_polling"
        health = build_source_health(
            "ws.shortlist",
            ok=not fallback,
            degraded_reason="; ".join(warnings[-5:]) if warnings and fallback else None,
            raw_ref=stopped_reason,
        )
        unique_users = {(sub.user or "").lower() for sub in plan.subscriptions if sub.user}
        return WebSocketRunReport(
            read_only=True,
            bounded_duration=True,
            duration_seconds=duration_seconds,
            subscription_count=len(plan.subscriptions),
            unique_user_count=len(unique_users),
            connected_sessions=connected_sessions,
            reconnect_count=reconnect_count,
            messages_received=messages_received,
            events_routed=len(router.events),
            snapshot_messages=snapshot_messages,
            duplicate_messages=duplicate_messages,
            heartbeat_count=heartbeat_count,
            fallback_to_rest_polling=fallback,
            stopped_reason=stopped_reason,
            warnings=warnings,
            source_health=[health],
        )

    def _run_refusal(
        self,
        subscriptions: list[Subscription],
        duration_seconds: int,
        reason: str,
        warnings: list[str] | None = None,
    ) -> WebSocketRunReport:
        unique_users = {(sub.user or "").lower() for sub in subscriptions if sub.user}
        warning_list = list(warnings or [])
        health = build_source_health(
            "ws.shortlist",
            ok=False,
            degraded_reason="; ".join(warning_list) if warning_list else reason,
            raw_ref=reason,
        )
        return WebSocketRunReport(
            read_only=True,
            bounded_duration=duration_seconds > 0,
            duration_seconds=duration_seconds,
            subscription_count=len(subscriptions),
            unique_user_count=len(unique_users),
            connected_sessions=0,
            reconnect_count=0,
            messages_received=0,
            events_routed=0,
            snapshot_messages=0,
            duplicate_messages=0,
            heartbeat_count=0,
            fallback_to_rest_polling=True,
            stopped_reason=reason,
            warnings=warning_list,
            source_health=[health],
        )


def _default_connector(url: str, *, timeout: float) -> Any:
    import websocket

    return websocket.create_connection(url, timeout=timeout, enable_multithread=True)


def _subscription_body(subscription: Subscription) -> dict[str, Any]:
    body: dict[str, Any] = {"type": subscription.stream_type.value}
    if subscription.user:
        body["user"] = subscription.user
    if subscription.coin:
        body["coin"] = subscription.coin
    return body


def _subscribe_payload(subscription: Subscription) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": _subscription_body(subscription)}


def _unsubscribe_payload(subscription: Subscription) -> dict[str, Any]:
    return {"method": "unsubscribe", "subscription": _subscription_body(subscription)}


def _safe_send(sock: Any, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "")
    if method not in _ALLOWED_OUTBOUND_METHODS:
        raise RuntimeError(f"Méthode WebSocket sortante interdite: {method or '<absente>'}")
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    lowered = encoded.casefold()
    if '"method":"post"' in lowered or '"type":"action"' in lowered or '"exchange"' in lowered:
        raise RuntimeError("Payload WebSocket potentiellement exécutable refusé.")
    sock.send(encoded)


def _decode_message(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        value = raw
    else:
        return None
    return value if isinstance(value, dict) else None


def _message_to_event(message: dict[str, Any]) -> StreamEvent | None:
    channel = str(message.get("channel") or message.get("type") or "")
    try:
        stream_type = StreamType(channel)
    except ValueError:
        return None
    data = message.get("data")
    if isinstance(data, dict):
        payload = dict(data)
    elif isinstance(data, list):
        payload = {"items": data}
    else:
        payload = {"value": data}
    is_snapshot = bool(payload.get("isSnapshot") or message.get("isSnapshot"))
    user = str(payload.get("user") or "") or None
    coin = str(payload.get("coin") or "") or None
    if coin is None and isinstance(payload.get("fills"), list) and payload["fills"]:
        first = payload["fills"][0]
        if isinstance(first, dict) and first.get("coin"):
            coin = str(first["coin"])
    canonical = json.dumps(message, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    event_id = f"ws:{hashlib.sha256(canonical).hexdigest()}"
    return now_event(
        event_id,
        stream_type,
        coin=coin,
        user=user,
        payload=payload,
        is_snapshot=is_snapshot,
    )


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or type(exc).__name__ in {
        "WebSocketTimeoutException",
        "TimeoutError",
    }


__all__ = [
    "MonitorPlan",
    "WebSocketManager",
    "WebSocketQaReport",
    "WebSocketRunReport",
]
