from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from hyper_smart_observer.copy_mode.copy_models import NoTradeDecision, NoTradeReason
from hyper_smart_observer.copy_mode.no_trade_report import decision_from_reason
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address


@dataclass(frozen=True)
class WalletFreshnessState:
    wallet_address: str
    last_position_at: datetime | None = None
    last_fill_at: datetime | None = None
    last_open_orders_at: datetime | None = None
    source: str = "realtime_monitor"
    warnings: list[str] = field(default_factory=list)

    @property
    def last_seen_at(self) -> datetime | None:
        values = [value for value in (self.last_position_at, self.last_fill_at, self.last_open_orders_at) if value]
        return max(values) if values else None


@dataclass(frozen=True)
class FreshnessDecision:
    allowed: bool
    wallet_address: str
    age_seconds: float | None
    reason: str
    no_trade: NoTradeDecision | None = None
    warnings: list[str] = field(default_factory=list)


class LivePositionFreshnessGuard:
    """Require fresh read-only wallet data before any follow simulation.

    This does not execute anything. It only decides whether a locally observed
    wallet state is fresh enough for research/paper replay. Stale data becomes
    a no-trade decision because following old positions is exactly how copy
    simulations become misleading.
    """

    def __init__(self, *, max_age_seconds: int = 20) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.max_age_seconds = max_age_seconds
        self._states: dict[str, WalletFreshnessState] = {}

    def update(
        self,
        wallet_address: str,
        *,
        position_at: datetime | None = None,
        fill_at: datetime | None = None,
        open_orders_at: datetime | None = None,
        source: str = "realtime_monitor",
    ) -> WalletFreshnessState:
        wallet = normalize_wallet_address(wallet_address)
        previous = self._states.get(wallet)
        state = WalletFreshnessState(
            wallet_address=wallet,
            last_position_at=_latest(previous.last_position_at if previous else None, position_at),
            last_fill_at=_latest(previous.last_fill_at if previous else None, fill_at),
            last_open_orders_at=_latest(previous.last_open_orders_at if previous else None, open_orders_at),
            source=source,
        )
        self._states[wallet] = state
        return state

    def evaluate(
        self,
        wallet_address: str,
        *,
        now: datetime | None = None,
        observed: str = "Position leader a suivre",
    ) -> FreshnessDecision:
        wallet = normalize_wallet_address(wallet_address)
        current = _aware(now or datetime.now(UTC))
        state = self._states.get(wallet)
        if state is None or state.last_seen_at is None:
            decision = decision_from_reason(
                NoTradeReason.SOURCE_UNAVAILABLE,
                observed=observed,
                leader_wallet=wallet,
                context={"freshness_required_seconds": self.max_age_seconds},
            )
            return FreshnessDecision(False, wallet, None, "NO_FRESH_WALLET_STATE", decision)
        age = (current - _aware(state.last_seen_at)).total_seconds()
        if age > self.max_age_seconds:
            decision = decision_from_reason(
                NoTradeReason.STALE_SIGNAL,
                observed=observed,
                leader_wallet=wallet,
                context={"age_seconds": age, "freshness_required_seconds": self.max_age_seconds},
            )
            return FreshnessDecision(False, wallet, age, "STALE_WALLET_STATE", decision)
        return FreshnessDecision(True, wallet, age, "FRESH_WALLET_STATE")


def _latest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(_aware(left), _aware(right))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
