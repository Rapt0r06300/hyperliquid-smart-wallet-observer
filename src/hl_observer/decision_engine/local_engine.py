from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.testnet.models import TestnetAction, TestnetOrderRequest, TestnetSide, unix_ms


class DecisionAction(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    REDUCE = "REDUCE"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class LocalDecision:
    action: DecisionAction
    reasons: list[str]
    candidate_id: str | None = None
    order_request: TestnetOrderRequest | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    decided_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        if self.order_request:
            data["order_request"] = self.order_request.to_dict()
        return data


@dataclass(slots=True)
class LocalDecisionEngine:
    settings: Settings

    def decide_from_candidate(
        self,
        candidate: SignalCandidate,
        *,
        notional_usdc: float,
        cloid: str,
    ) -> LocalDecision:
        risk_context = RiskContext(
            spread_bps=candidate.estimated_spread_bps,
            estimated_slippage_bps=candidate.estimated_slippage_bps,
            orderbook_depth_usdc=candidate.orderbook_depth_usdc,
            wallet_score=candidate.wallet_score,
            signal_score=candidate.signal_score,
            edge_remaining_bps=candidate.edge_remaining_bps,
            signal_age_ms=candidate.signal_age_ms,
        )
        risk_decision = RiskEngine(self.settings).evaluate(risk_context)
        evidence = {
            "candidate": candidate.model_dump(mode="json"),
            "risk_decision": risk_decision.model_dump(mode="json"),
            "decision_layer": "local_decision_engine",
        }
        if not risk_decision.allowed:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=list(risk_decision.reasons),
                candidate_id=candidate.id,
                evidence=evidence,
            )

        action = self._action_from_signal(candidate.signal_type)
        if action is DecisionAction.NO_TRADE:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=["signal type is not executable in testnet mode"],
                candidate_id=candidate.id,
                evidence=evidence,
            )

        side = TestnetSide.LONG if candidate.side == "long" else TestnetSide.SHORT
        if action is DecisionAction.ENTER:
            testnet_action = TestnetAction.OPEN
            reduce_only = False
            request_notional = notional_usdc
        elif action is DecisionAction.REDUCE:
            testnet_action = TestnetAction.REDUCE
            reduce_only = True
            request_notional = notional_usdc
        elif action is DecisionAction.EXIT:
            testnet_action = TestnetAction.CLOSE
            reduce_only = True
            request_notional = 0.0
        else:
            return LocalDecision(
                action=DecisionAction.NO_TRADE,
                reasons=["signal action cannot be converted to a testnet request"],
                candidate_id=candidate.id,
                evidence=evidence,
            )
        request = TestnetOrderRequest(
            cloid=cloid,
            action=testnet_action,
            coin=candidate.coin,
            side=side,
            notional_usdc=request_notional,
            limit_price=candidate.observed_price,
            reduce_only=reduce_only,
            source_signal_id=candidate.id,
            evidence=evidence,
        )
        return LocalDecision(
            action=action,
            reasons=["risk gates passed; prepared testnet request"],
            candidate_id=candidate.id,
            order_request=request,
            evidence=evidence,
        )

    @staticmethod
    def _action_from_signal(signal_type: str) -> DecisionAction:
        normalized = signal_type.lower()
        if normalized in {"open", "add"}:
            return DecisionAction.ENTER
        if normalized == "reduce":
            return DecisionAction.REDUCE
        if normalized == "close":
            return DecisionAction.EXIT
        return DecisionAction.NO_TRADE
