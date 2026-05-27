from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address
from hyper_smart_observer.realtime_monitor.stream_models import StreamType


USER_SPECIFIC = {
    StreamType.USER_FILLS,
    StreamType.USER_EVENTS,
    StreamType.ORDER_UPDATES,
    StreamType.OPEN_ORDERS,
    StreamType.CLEARINGHOUSE_STATE,
}


@dataclass(frozen=True)
class Subscription:
    stream_type: StreamType
    coin: str | None = None
    user: str | None = None

    @property
    def stream(self) -> StreamType:
        return self.stream_type

    def key(self) -> str:
        return f"{self.stream_type.value}:{self.coin or ''}:{(self.user or '').lower()}"


@dataclass(frozen=True)
class SubscriptionPlan:
    accepted: list[Subscription] = field(default_factory=list)
    rejected: list[Subscription] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SubscriptionPlanner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def validate(self, subscriptions: list[Subscription]) -> list[Subscription]:
        plan = self.plan(subscriptions)
        if plan.rejected:
            raise ValueError("; ".join(plan.warnings))
        return plan.accepted

    def plan(self, subscriptions: list[Subscription]) -> SubscriptionPlan:
        accepted: list[Subscription] = []
        rejected: list[Subscription] = []
        warnings: list[str] = []
        seen_users: set[str] = set()
        for sub in subscriptions:
            if len(accepted) >= self.config.ws_max_subscriptions:
                rejected.append(sub)
                warnings.append("too many websocket subscriptions")
                continue
            if sub.stream_type in USER_SPECIFIC and sub.user:
                user = normalize_wallet_address(sub.user)
                if user not in seen_users and len(seen_users) >= self.config.ws_max_user_subscriptions:
                    rejected.append(sub)
                    warnings.append("too many unique user websocket subscriptions")
                    continue
                seen_users.add(user)
            accepted.append(sub)
        return SubscriptionPlan(accepted=accepted, rejected=rejected, warnings=warnings)
