"""Paper-only execution connector."""

from __future__ import annotations

from hashlib import sha256

from .standard import PaperOrderRequest, PaperOrderResult


class LocalPaperExecutionConnector:
    def submit_paper_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        if float(request.notional_usdt) <= 0:
            return PaperOrderResult(
                False,
                "",
                "INVALID_NOTIONAL",
                coin=str(request.coin).upper(),
                side=str(request.side).upper(),
                notional_usdt=float(request.notional_usdt),
                action=str(request.action or "OPEN").upper(),
                order_type=request.order_type,
                strategy_id=request.strategy_id,
                reference_price=float(request.reference_price or 0.0),
                metadata=dict(request.metadata),
            )
        material = (
            f"{request.strategy_id}|{request.coin}|{request.side}|"
            f"{request.notional_usdt}|{request.action}|{request.order_type}|{request.reference_price}"
        )
        order_id = "paper:" + sha256(material.encode("utf-8")).hexdigest()[:24]
        return PaperOrderResult(
            True,
            order_id,
            "ACCEPT_PAPER_ORDER",
            coin=str(request.coin).upper(),
            side=str(request.side).upper(),
            notional_usdt=float(request.notional_usdt),
            action=str(request.action or "OPEN").upper(),
            order_type=request.order_type,
            strategy_id=request.strategy_id,
            reference_price=float(request.reference_price or 0.0),
            metadata=dict(request.metadata),
        )


__all__ = ["LocalPaperExecutionConnector"]
