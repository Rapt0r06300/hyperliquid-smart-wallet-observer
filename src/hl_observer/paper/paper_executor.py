from __future__ import annotations

import hashlib

from hl_observer.hyperliquid.schemas import PaperOrder, RiskDecision, SignalCandidate, SignalDecision
from hl_observer.paper.pessimistic_fill_model import pessimistic_fill_price
from hl_observer.paper.partial_fill_model import acceptance_before_fill, market_depth_fill_receipt


class PaperExecutor:
    def __init__(self, fee_bps: float = 4.0) -> None:
        self.fee_bps = fee_bps
        self.orders: list[PaperOrder] = []

    def submit(
        self,
        signal: SignalCandidate,
        risk_decision: RiskDecision,
        *,
        notional_usdc: float,
        market_depth: list[dict[str, object]] | None = None,
        accepted_ts_ms: int | None = None,
        fill_ts_ms: int | None = None,
    ) -> PaperOrder:
        order_id = hashlib.sha256(f"{signal.id}:{len(self.orders)}".encode()).hexdigest()[:16]
        if not risk_decision.allowed:
            order = PaperOrder(
                order_id=order_id,
                signal_id=signal.id,
                coin=signal.coin,
                side="buy" if signal.side == "long" else "sell",
                notional_usdc=0.0,
                requested_price=signal.observed_price,
                simulated_fill_price=signal.observed_price,
                fee_bps=self.fee_bps,
                slippage_bps=signal.estimated_slippage_bps,
                decision=risk_decision.decision,
                rejected_reason="; ".join(risk_decision.reasons),
            )
            self.orders.append(order)
            return order

        if market_depth is not None:
            if accepted_ts_ms is None or fill_ts_ms is None:
                return self._rejected_order(signal, risk_decision, order_id, "ACCEPTANCE_OR_FILL_TIMESTAMP_MISSING")
            temporal = acceptance_before_fill(accepted_ts_ms=accepted_ts_ms, fill_ts_ms=fill_ts_ms)
            if temporal.get("accepted") is not True:
                return self._rejected_order(signal, risk_decision, order_id, str(temporal.get("reason")))
            depth = market_depth_fill_receipt(
                side="buy" if signal.side == "long" else "sell",
                order_notional_usdc=notional_usdc,
                levels=market_depth,
            )
            if depth.get("filled") is not True:
                return self._rejected_order(signal, risk_decision, order_id, str(depth.get("reason")))
            notional_usdc = float(depth["filled_notional_usdc"])

        fill_price = pessimistic_fill_price(
            signal.side,
            signal.observed_price,
            signal.estimated_spread_bps,
            signal.estimated_slippage_bps,
        )
        order = PaperOrder(
            order_id=order_id,
            signal_id=signal.id,
            coin=signal.coin,
            side="buy" if signal.side == "long" else "sell",
            notional_usdc=notional_usdc,
            requested_price=signal.observed_price,
            simulated_fill_price=fill_price,
            fee_bps=self.fee_bps,
            slippage_bps=signal.estimated_slippage_bps,
            decision=SignalDecision.PAPER_TRADE,
        )
        self.orders.append(order)
        return order

    def _rejected_order(self, signal: SignalCandidate, risk_decision: RiskDecision, order_id: str, reason: str) -> PaperOrder:
        order = PaperOrder(
            order_id=order_id,
            signal_id=signal.id,
            coin=signal.coin,
            side="buy" if signal.side == "long" else "sell",
            notional_usdc=0.0,
            requested_price=signal.observed_price,
            simulated_fill_price=signal.observed_price,
            fee_bps=self.fee_bps,
            slippage_bps=signal.estimated_slippage_bps,
            decision=SignalDecision.OBSERVE_ONLY,
            rejected_reason=reason,
        )
        self.orders.append(order)
        return order
