"""Paper-only connector facade for strategy intents.

This is the safe half of the Hummingbot-style connector split: read-only
connectors observe markets, while this connector applies already-approved
``PaperIntent`` objects to a local simulated ledger. It never talks to a venue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256

from hl_observer.paper_trading.exec_model import ExecModelConfig, ExecResult, simulate_depth_execution, simulate_execution
from hl_observer.strategies.models import ApprovedPaperIntent, IntentAction, IntentSide, is_actionable


@dataclass(frozen=True, slots=True)
class PaperSimFill:
    fill_id: str
    strategy_id: str
    coin: str
    side: str
    action: str
    notional_usdt: float
    mid_price: float
    fill_price: float
    net_cost_bps: float
    source: str = "paper_sim_connector"


@dataclass(frozen=True, slots=True)
class PaperSimConnectorResult:
    accepted: bool
    fill: PaperSimFill | None
    reason_codes: tuple[str, ...]
    evidence: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "fill": asdict(self.fill) if self.fill else None,
            "reason_codes": list(self.reason_codes),
            "evidence": dict(self.evidence),
            "paper_only": True,
            "external_action": False,
        }


class PaperSimConnector:
    """Apply risk-approved intents to local paper fill simulation only."""

    read_only = False
    paper_only = True
    external_action = False
    name = "paper_sim_connector"

    def __init__(self, *, exec_config: ExecModelConfig | None = None) -> None:
        self.exec_config = exec_config or ExecModelConfig()
        self._fills: list[PaperSimFill] = []

    @property
    def fills(self) -> tuple[PaperSimFill, ...]:
        return tuple(self._fills)

    def apply_intent(
        self,
        approved_intent: ApprovedPaperIntent,
        *,
        mid_price: float,
        top_depth_usdt: float | None,
        observed_at_ms: int,
        asks: tuple[tuple[float, float], ...] = (),
        bids: tuple[tuple[float, float], ...] = (),
        min_fill_ratio: float = 0.85,
    ) -> PaperSimConnectorResult:
        if not is_actionable(approved_intent):
            return _reject("RISK_NOT_APPROVED", approved_intent, observed_at_ms=observed_at_ms)
        intent = approved_intent.intent
        if mid_price <= 0:
            return _reject("MARKET_PRICE_INVALID", approved_intent, observed_at_ms=observed_at_ms)
        if intent.action not in {IntentAction.OPEN, IntentAction.ADD, IntentAction.REDUCE, IntentAction.CLOSE}:
            return _reject("PAPER_ACTION_UNSUPPORTED", approved_intent, observed_at_ms=observed_at_ms)

        side = _execution_side(intent.side, intent.action)
        if side is None:
            return _reject("PAPER_SIDE_UNSUPPORTED", approved_intent, observed_at_ms=observed_at_ms)

        notional = max(0.0, float(intent.target_notional_usdt or 0.0))
        if notional <= 0:
            return _reject("PAPER_NOTIONAL_MISSING", approved_intent, observed_at_ms=observed_at_ms)

        depth_result = None
        if asks or bids:
            depth_result = simulate_depth_execution(
                side=side,
                notional_usdc=notional,
                mid_price=float(mid_price),
                asks=asks,
                bids=bids,
                min_fill_ratio=min_fill_ratio,
            )
            if depth_result.missed:
                rejected = _reject(depth_result.reason, approved_intent, observed_at_ms=observed_at_ms)
                rejected.evidence.update({"depth_execution": asdict(depth_result)})
                return rejected
            if depth_result.average_fill_price is not None:
                mid_price = depth_result.average_fill_price
                top_depth_usdt = max(float(top_depth_usdt or 0.0), depth_result.filled_notional_usdc)

        exec_result = simulate_execution(
            side=side,
            notional_usdc=notional,
            mid_price=float(mid_price),
            top_depth_usdc=top_depth_usdt,
            is_maker=False,
            config=self.exec_config,
        )
        fill = PaperSimFill(
            fill_id=_fill_id(intent.strategy_id, intent.coin, intent.action.value, observed_at_ms, exec_result),
            strategy_id=intent.strategy_id,
            coin=str(intent.coin).upper(),
            side=side,
            action=intent.action.value,
            notional_usdt=round(notional, 8),
            mid_price=round(float(mid_price), 10),
            fill_price=exec_result.fill_price,
            net_cost_bps=round(exec_result.net_cost_bps, 8),
        )
        self._fills.append(fill)
        return PaperSimConnectorResult(
            accepted=True,
            fill=fill,
            reason_codes=(),
            evidence={
                "source": self.name,
                "paper_only": True,
                "external_action": False,
                "observed_at_ms": int(observed_at_ms),
                "top_depth_usdt": top_depth_usdt,
                "risk_reasons": list(approved_intent.risk_reasons),
                "exec_model": asdict(exec_result),
                "depth_execution": asdict(depth_result) if depth_result else None,
            },
        )


def _reject(
    reason: str,
    approved_intent: ApprovedPaperIntent,
    *,
    observed_at_ms: int,
) -> PaperSimConnectorResult:
    intent = approved_intent.intent
    return PaperSimConnectorResult(
        accepted=False,
        fill=None,
        reason_codes=(reason, *tuple(approved_intent.risk_reasons or ())),
        evidence={
            "source": PaperSimConnector.name,
            "paper_only": True,
            "external_action": False,
            "observed_at_ms": int(observed_at_ms),
            "strategy_id": intent.strategy_id,
            "coin": intent.coin,
            "action": intent.action.value,
        },
    )


def _execution_side(side: IntentSide, action: IntentAction) -> str | None:
    if action in {IntentAction.OPEN, IntentAction.ADD}:
        if side is IntentSide.LONG:
            return "BUY"
        if side is IntentSide.SHORT:
            return "SELL"
    if action in {IntentAction.REDUCE, IntentAction.CLOSE}:
        if side is IntentSide.LONG:
            return "SELL"
        if side is IntentSide.SHORT:
            return "BUY"
    return None


def _fill_id(strategy_id: str, coin: str, action: str, observed_at_ms: int, exec_result: ExecResult) -> str:
    blob = f"{strategy_id}|{coin}|{action}|{observed_at_ms}|{exec_result.fill_price}|{exec_result.notional_usdc}"
    return "psim_" + sha256(blob.encode("utf-8")).hexdigest()[:20]


__all__ = ["PaperSimConnector", "PaperSimConnectorResult", "PaperSimFill"]
