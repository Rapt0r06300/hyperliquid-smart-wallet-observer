"""Reference paper strategies (V12 capability M).

Minimal, deterministic, pure strategies that build a ``PaperIntent`` from already
observed real data. No network, no I/O, no order. Each ``propose`` returns a
simulation-only intent (or ``None`` = no opportunity); the intent still has to go
through :func:`hl_observer.strategies.models.approve_with_risk`.
"""

from __future__ import annotations

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    StrategyDefinition,
    StrategyKind,
    make_strategy,
)


class _BasePaperStrategy:
    kind: StrategyKind

    def __init__(self, definition: StrategyDefinition) -> None:
        if definition.kind is not self.kind:
            raise ValueError(f"definition kind {definition.kind} != {self.kind}")
        self.definition = definition

    @property
    def strategy_id(self) -> str:
        return self.definition.strategy_id


class CopyFollowStrategy(_BasePaperStrategy):
    """Follow a fresh, positive-edge leader move — paper intent only."""

    kind = StrategyKind.COPY_FOLLOW

    @classmethod
    def default(cls) -> "CopyFollowStrategy":
        return cls(make_strategy(
            strategy_id="copy_follow", version=1, kind=cls.kind,
            name="Copy follow", params={"min_edge_bps": 10, "max_age_ms": 30000},
        ))

    def propose(
        self,
        *,
        coin: str,
        leader_side: IntentSide,
        edge_net_bps: float,
        signal_age_ms: int,
        context: RunContext = RunContext.LIVE,
        now_ms: int = 0,
    ) -> PaperIntent | None:
        min_edge = float(self.definition.params.get("min_edge_bps", 10))
        max_age = int(self.definition.params.get("max_age_ms", 30000))
        if leader_side is IntentSide.FLAT:
            return None
        if signal_age_ms > max_age:
            return None  # NO_TRADE: stale signal
        if edge_net_bps < min_edge:
            return None  # NO_TRADE: edge too thin
        return PaperIntent(
            strategy_id=self.strategy_id,
            coin=coin,
            side=leader_side,
            action=IntentAction.OPEN,
            confidence=min(1.0, edge_net_bps / 50.0),
            context=context,
            reasons=(f"edge_net_bps={edge_net_bps:.1f}", f"age_ms={signal_age_ms}"),
            created_at_ms=now_ms,
        )


class MarketMakingSimStrategy(_BasePaperStrategy):
    """Quote-around-mid simulation: orderbook imbalance -> directional paper intent."""

    kind = StrategyKind.MARKET_MAKING_SIM

    @classmethod
    def default(cls) -> "MarketMakingSimStrategy":
        return cls(make_strategy(
            strategy_id="market_making_sim", version=1, kind=cls.kind,
            name="Market making (sim)", params={"min_imbalance": 0.15},
        ))

    def propose(
        self,
        *,
        coin: str,
        bid_depth: float,
        ask_depth: float,
        context: RunContext = RunContext.LIVE,
        now_ms: int = 0,
    ) -> PaperIntent | None:
        total = bid_depth + ask_depth
        if total <= 0:
            return None
        imbalance = (bid_depth - ask_depth) / total
        threshold = float(self.definition.params.get("min_imbalance", 0.15))
        if abs(imbalance) < threshold:
            return None  # NO_TRADE: book balanced
        side = IntentSide.LONG if imbalance > 0 else IntentSide.SHORT
        return PaperIntent(
            strategy_id=self.strategy_id,
            coin=coin,
            side=side,
            action=IntentAction.OPEN,
            confidence=min(1.0, abs(imbalance)),
            context=context,
            reasons=(f"imbalance={imbalance:+.2f}",),
            created_at_ms=now_ms,
        )


__all__ = ["CopyFollowStrategy", "MarketMakingSimStrategy"]
