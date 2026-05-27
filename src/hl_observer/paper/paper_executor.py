from __future__ import annotations

import hashlib

from hl_observer.hyperliquid.schemas import PaperOrder, RiskDecision, SignalCandidate, SignalDecision
from hl_observer.paper.pessimistic_fill_model import pessimistic_fill_price


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
                slippage_bps=signal.slippage_bps,
                decision=risk_decision.decision,
                rejected_reason="; ".join(risk_decision.reasons),
            )
            self.orders.append(order)
            return order

        fill_price = pessimistic_fill_price(
            signal.side,
            signal.observed_price,
            signal.spread_bps,
            signal.slippage_bps,
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
            slippage_bps=signal.slippage_bps,
            decision=SignalDecision.PAPER_TRADE,
        )
        self.orders.append(order)
        return order
