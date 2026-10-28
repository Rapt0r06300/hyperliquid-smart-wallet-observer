from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import Settings
from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.journal import TestnetDecisionJournal
from hl_observer.testnet.models import (
    TestnetAction,
    TestnetOrderRequest,
    TestnetOrderResult,
    TestnetPortfolioSnapshot,
    TestnetSide,
)
from hl_observer.testnet.safety import TESTNET_DISABLED_REASON


@dataclass(slots=True)
class TestnetExecutor:
    """Compatibility surface that refuses every testnet action without adapter access."""

    settings: Settings
    adapter: TestnetExchangeAdapter
    journal: TestnetDecisionJournal

    def open_position(
        self,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
    ) -> TestnetOrderResult:
        del confirmed
        if request.action is not TestnetAction.OPEN:
            raise ValueError("open_position requires action=open")
        return self._refuse(request)

    def reduce_position(
        self,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
    ) -> TestnetOrderResult:
        del confirmed
        if request.action is not TestnetAction.REDUCE:
            raise ValueError("reduce_position requires action=reduce")
        return self._refuse(request)

    def close_position(
        self,
        coin: str,
        side: TestnetSide,
        *,
        cloid: str,
        confirmed: bool,
        evidence: dict | None = None,
    ) -> TestnetOrderResult:
        del confirmed
        request = TestnetOrderRequest(
            cloid=cloid,
            action=TestnetAction.CLOSE,
            coin=coin,
            side=side,
            notional_usdc=0.0,
            limit_price=0.0,
            reduce_only=True,
            evidence=evidence or {},
        )
        return self._refuse(request)

    def get_portfolio(self) -> TestnetPortfolioSnapshot:
        raise RuntimeError(TESTNET_DISABLED_REASON)

    def apply_exit_plan(
        self,
        *,
        confirmed: bool,
        mark_prices: dict[str, float],
    ) -> list[TestnetOrderResult]:
        del confirmed, mark_prices
        raise RuntimeError(TESTNET_DISABLED_REASON)

    def _refuse(self, request: TestnetOrderRequest) -> TestnetOrderResult:
        reasons = [TESTNET_DISABLED_REASON]
        self.journal.write_guard_refusal(reasons, evidence=request.evidence)
        return TestnetOrderResult(
            status="rejected",
            adapter="disabled_by_scope",
            environment="testnet",
            request=request,
            reasons=reasons,
        )
