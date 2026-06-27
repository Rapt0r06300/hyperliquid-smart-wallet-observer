from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.pipeline.source_health import SourceHealth, build_source_health
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription, SubscriptionPlanner


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
        """Return a read-only QA report for WS monitoring readiness.

        This method does not connect to a socket. It proves that a requested WS
        plan is bounded and gives the runtime an explicit fallback to REST
        polling when the plan is disabled, invalid, or empty.
        """

        plan = self.build_plan(subscriptions, dry_run=dry_run, duration_seconds=duration_seconds)
        bounded = duration_seconds is not None and duration_seconds > 0
        unique_users = {
            (sub.user or "").lower()
            for sub in plan.subscriptions
            if sub.user
        }
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
