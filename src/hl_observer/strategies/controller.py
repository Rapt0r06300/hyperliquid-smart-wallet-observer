"""Strategy controller that can only route to paper connectors."""

from __future__ import annotations

from dataclasses import dataclass, replace

from hl_observer.connectors.standard import PaperExecutionConnector, PaperOrderRequest, PaperOrderResult


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    strategy_id: str
    request: PaperOrderRequest


class StrategyController:
    def __init__(self, execution_connector: PaperExecutionConnector) -> None:
        self.execution_connector = execution_connector

    def run_once(self, decision: StrategyDecision) -> PaperOrderResult:
        request = decision.request
        if not request.strategy_id:
            request = replace(request, strategy_id=decision.strategy_id)
        return self.execution_connector.submit_paper_order(request)


__all__ = ["StrategyController", "StrategyDecision"]
