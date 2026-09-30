"""Strategy models (V12 capability M — Strategy registry paper-only).

A strategy is a *recipe* that, given observed real data, proposes a
``PaperIntent`` — a simulated action only. A strategy can NEVER place an order,
sign, deposit, or touch real money: ``PaperIntent.simulation_only`` is forced to
True and there is no execution surface anywhere in this package.

A ``PaperIntent`` is also never directly actionable: it carries
``requires_risk_approval=True`` and only becomes an ``ApprovedPaperIntent`` by
passing through the risk layer via :func:`approve_with_risk`. This encodes the
V12 rule "every strategy goes through the risk engine".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from hashlib import sha256

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - py<3.11 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from hl_observer.storage.run_context import RunContext

_ALL_PAPER_CONTEXTS: tuple[RunContext, ...] = (
    RunContext.LIVE,
    RunContext.BACKTEST,
    RunContext.REPLAY,
    RunContext.TEST_FIXTURE,
)


class StrategyKind(StrEnum):
    COPY_FOLLOW = "COPY_FOLLOW"
    ORDERBOOK_IMBALANCE = "ORDERBOOK_IMBALANCE"
    ARBITRAGE_SIM = "ARBITRAGE_SIM"
    MARKET_MAKING_SIM = "MARKET_MAKING_SIM"
    DIRECTION_HUNT = "DIRECTION_HUNT"
    SPREAD_FARM = "SPREAD_FARM"
    WHALE_ALERT = "WHALE_ALERT"
    FAST_TIMING = "FAST_TIMING"
    # V10.7 strategies (paper-only)
    FADE_IMPULSE = "FADE_IMPULSE"
    FOLLOW_IMPULSE = "FOLLOW_IMPULSE"
    MEAN_REVERSION = "MEAN_REVERSION"
    MOMENTUM = "MOMENTUM"
    VOLATILITY_BREAKOUT = "VOLATILITY_BREAKOUT"
    LOW_VOL_SCALPING = "LOW_VOL_SCALPING"
    CROSS_SOURCE_DISCREPANCY = "CROSS_SOURCE_DISCREPANCY"
    DCA_SIM = "DCA_SIM"
    KELLY_SIZING = "KELLY_SIZING"
    STRATEGY_ENSEMBLE = "STRATEGY_ENSEMBLE"
    SHADOW_MODEL = "SHADOW_MODEL"
    RAG_EVIDENCE_CONTEXT = "RAG_EVIDENCE_CONTEXT"


class StrategyState(StrEnum):
    ACTIVE = "ACTIVE"
    SHADOW = "SHADOW"
    KILLED = "KILLED"
    LEGACY = "LEGACY"


class StrategyLane(StrEnum):
    STRICT = "STRICT"
    EXPERIMENTAL = "EXPERIMENTAL"


class IntentSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class IntentAction(StrEnum):
    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class PaperIntent:
    """A proposed *simulated* action. Never an order, never actionable as-is."""

    strategy_id: str
    coin: str
    side: IntentSide
    action: IntentAction
    target_notional_usdt: float = 0.0
    confidence: float = 0.0
    context: RunContext = RunContext.LIVE
    reasons: tuple[str, ...] = ()
    created_at_ms: int = 0
    simulation_only: bool = True
    requires_risk_approval: bool = True

    def __post_init__(self) -> None:
        if self.simulation_only is not True:
            raise ValueError("PaperIntent is paper-only: simulation_only cannot be disabled")
        if self.requires_risk_approval is not True:
            raise ValueError("PaperIntent must require risk approval")


# Private sentinel: an ApprovedPaperIntent can only be built via approve_with_risk.
_APPROVAL_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ApprovedPaperIntent:
    """A PaperIntent that has passed the risk layer. Still simulation-only."""

    intent: PaperIntent
    risk_ok: bool
    risk_reasons: tuple[str, ...] = ()
    _token: object = None

    def __post_init__(self) -> None:
        if self._token is not _APPROVAL_TOKEN:
            raise ValueError(
                "ApprovedPaperIntent must be created via approve_with_risk() — "
                "strategies cannot bypass the risk engine"
            )


def approve_with_risk(
    intent: PaperIntent,
    risk_fn: Callable[[PaperIntent], tuple[bool, Sequence[str]]],
) -> ApprovedPaperIntent:
    """Route a strategy's PaperIntent through the risk engine callable.

    ``risk_fn`` returns ``(ok, reasons)``. This is the *only* way to obtain an
    ApprovedPaperIntent, so no strategy can skip risk.
    """
    ok, reasons = risk_fn(intent)
    return ApprovedPaperIntent(
        intent=intent,
        risk_ok=bool(ok),
        risk_reasons=tuple(reasons or ()),
        _token=_APPROVAL_TOKEN,
    )


def approve_with_risk_and_gate(
    intent: PaperIntent,
    risk_fn: Callable[[PaperIntent], tuple[bool, Sequence[str]]],
    gate_fn: Callable[[PaperIntent], tuple[bool, Sequence[str]]] | None = None,
) -> ApprovedPaperIntent:
    """Comme :func:`approve_with_risk`, mais compose AUSSI un gate d'entree optionnel.

    ``gate_fn`` (defaut None = inactif) renvoie ``(ok, reasons)``. L'intent n'est
    approuve que si le risk ET le gate passent. Additif et deny-by-default : sans
    ``gate_fn`` le comportement est identique a ``approve_with_risk``. Reste
    simulation-only ; un refus est un NO_TRADE, jamais un ordre.
    """
    risk_ok, risk_reasons = risk_fn(intent)
    gate_ok, gate_reasons = (True, ()) if gate_fn is None else gate_fn(intent)
    return ApprovedPaperIntent(
        intent=intent,
        risk_ok=bool(risk_ok) and bool(gate_ok),
        risk_reasons=tuple(risk_reasons or ()) + tuple(gate_reasons or ()),
        _token=_APPROVAL_TOKEN,
    )


def is_actionable(obj: object) -> bool:
    """Only a risk-approved, simulation-only intent is actionable (by the paper engine)."""
    return (
        isinstance(obj, ApprovedPaperIntent)
        and obj.risk_ok
        and obj.intent.simulation_only is True
        and obj.intent.action is not IntentAction.NONE
    )


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    version: int
    kind: StrategyKind
    name: str = ""
    description: str = ""
    enabled: bool = True
    contexts: tuple[RunContext, ...] = _ALL_PAPER_CONTEXTS
    tags: tuple[str, ...] = ()
    read_only: bool = True
    params_items: tuple[tuple[str, str], ...] = ()
    family: str = "UNSPECIFIED"
    state: StrategyState = StrategyState.ACTIVE
    can_open_strict: bool = True
    can_open_experimental: bool = True
    multi_leg_execution_ready: bool = False

    def __post_init__(self) -> None:
        if self.read_only is not True:
            raise ValueError("strategies are paper-only / read-only by construction")
        if int(self.version) < 1:
            raise ValueError("strategy version must be >= 1")
        if self.state is not StrategyState.ACTIVE and self.can_open_strict:
            raise ValueError("only ACTIVE strategies may open in the STRICT ledger")
        if self.state in {StrategyState.KILLED, StrategyState.LEGACY} and (
            self.can_open_strict or self.can_open_experimental
        ):
            raise ValueError("KILLED/LEGACY strategies cannot open a paper position")
        if (
            self.kind in {StrategyKind.ARBITRAGE_SIM, StrategyKind.CROSS_SOURCE_DISCREPANCY}
            and not self.multi_leg_execution_ready
            and (self.can_open_strict or self.can_open_experimental)
        ):
            raise ValueError("multi-leg diagnostics cannot open before realistic execution is ready")

    @property
    def params(self) -> dict[str, str]:
        return dict(self.params_items)

    @property
    def params_hash(self) -> str:
        blob = repr((self.strategy_id, self.version, self.kind.value, self.params_items))
        return sha256(blob.encode("utf-8")).hexdigest()[:16]

    @property
    def key(self) -> str:
        return f"{self.strategy_id}@v{self.version}"

    def valid_in(self, context: RunContext) -> bool:
        return context in self.contexts

    def can_open(self, lane: StrategyLane) -> bool:
        if not self.enabled or self.state in {StrategyState.KILLED, StrategyState.LEGACY}:
            return False
        if lane is StrategyLane.STRICT:
            return self.state is StrategyState.ACTIVE and self.can_open_strict
        return self.can_open_experimental


def make_strategy(
    *,
    strategy_id: str,
    version: int,
    kind: StrategyKind,
    name: str = "",
    description: str = "",
    enabled: bool = True,
    contexts: Sequence[RunContext] | None = None,
    tags: Sequence[str] = (),
    params: dict[str, object] | None = None,
    family: str = "",
    state: StrategyState | None = None,
    can_open_strict: bool | None = None,
    can_open_experimental: bool | None = None,
    multi_leg_execution_ready: bool = False,
) -> StrategyDefinition:
    items = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))
    ctxs = tuple(contexts) if contexts else _ALL_PAPER_CONTEXTS
    strategy_text = str(strategy_id).lower()
    diagnostic_multi_leg = kind in {
        StrategyKind.ARBITRAGE_SIM,
        StrategyKind.CROSS_SOURCE_DISCREPANCY,
    }
    carry_or_funding = "carry" in strategy_text or "funding" in strategy_text
    external = strategy_text.startswith("ext_")
    inferred_state = state or (
        StrategyState.SHADOW
        if external or carry_or_funding or (diagnostic_multi_leg and not multi_leg_execution_ready)
        else StrategyState.ACTIVE
    )
    inferred_strict = (
        inferred_state is StrategyState.ACTIVE
        and not carry_or_funding
        and (not diagnostic_multi_leg or multi_leg_execution_ready)
        if can_open_strict is None
        else bool(can_open_strict)
    )
    inferred_experimental = (
        inferred_state not in {StrategyState.KILLED, StrategyState.LEGACY}
        and not carry_or_funding
        and (not diagnostic_multi_leg or multi_leg_execution_ready)
        if can_open_experimental is None
        else bool(can_open_experimental)
    )
    return StrategyDefinition(
        strategy_id=strategy_id,
        version=int(version),
        kind=kind,
        name=name,
        description=description,
        enabled=enabled,
        contexts=ctxs,
        tags=tuple(tags),
        params_items=items,
        family=str(family or kind.value),
        state=inferred_state,
        can_open_strict=inferred_strict,
        can_open_experimental=inferred_experimental,
        multi_leg_execution_ready=bool(multi_leg_execution_ready),
    )


__all__ = [
    "StrategyKind",
    "StrategyState",
    "StrategyLane",
    "IntentSide",
    "IntentAction",
    "PaperIntent",
    "ApprovedPaperIntent",
    "StrategyDefinition",
    "approve_with_risk",
    "approve_with_risk_and_gate",
    "is_actionable",
    "make_strategy",
]
