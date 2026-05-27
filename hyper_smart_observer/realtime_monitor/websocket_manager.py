from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription, SubscriptionPlanner


@dataclass(frozen=True)
class MonitorPlan:
    dry_run: bool
    duration_seconds: int | None
    subscriptions: list[Subscription]
    read_only: bool = True
    warnings: list[str] = field(default_factory=list)


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
