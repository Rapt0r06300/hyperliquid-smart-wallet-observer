from __future__ import annotations

from dataclasses import dataclass
from time import sleep

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
from hl_observer.testnet.safety import TestnetSafetyGuard


@dataclass(slots=True)
class TestnetExecutor:
    settings: Settings
    adapter: TestnetExchangeAdapter
    journal: TestnetDecisionJournal
    guard: TestnetSafetyGuard | None = None
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        if self.guard is None:
            self.guard = TestnetSafetyGuard()

    def open_position(
        self,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
    ) -> TestnetOrderResult:
        if request.action is not TestnetAction.OPEN:
            raise ValueError("open_position requires action=open")
        return self._submit(request, confirmed=confirmed)

    def reduce_position(
        self,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
    ) -> TestnetOrderResult:
        if request.action is not TestnetAction.REDUCE:
            raise ValueError("reduce_position requires action=reduce")
        return self._submit(request, confirmed=confirmed)

    def close_position(
        self,
        coin: str,
        side: TestnetSide,
        *,
        cloid: str,
        confirmed: bool,
        evidence: dict | None = None,
    ) -> TestnetOrderResult:
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
        decision = self.guard.evaluate(  # type: ignore[union-attr]
            self.settings,
            self.adapter,
            request,
            confirmed=confirmed,
            open_positions=self.adapter.get_testnet_positions(),
        )
        if not decision.allowed:
            self.journal.write_guard_refusal(decision.reasons, evidence=evidence)
            return TestnetOrderResult(
                status="rejected",
                adapter=self.adapter.name,
                environment="testnet",
                request=request,
                reasons=decision.reasons,
            )
        result = self.adapter.place_testnet_order(request)
        self.journal.write_result(result, evidence=evidence)
        return result

    def get_portfolio(self) -> TestnetPortfolioSnapshot:
        return self.adapter.get_testnet_pnl()

    def apply_exit_plan(
        self,
        *,
        confirmed: bool,
        mark_prices: dict[str, float],
    ) -> list[TestnetOrderResult]:
        """Apply local SL/TP/trailing exit checks to open testnet positions."""

        results: list[TestnetOrderResult] = []
        for position in self.adapter.get_testnet_positions():
            mark = mark_prices.get(position.coin, position.mark_price)
            pnl = (mark - position.entry_price) * position.size
            if position.side is TestnetSide.SHORT:
                pnl = (position.entry_price - mark) * position.size
            evidence = {
                "exit_check": "local_sltp_trailing_guard",
                "coin": position.coin,
                "mark_price": mark,
                "entry_price": position.entry_price,
                "unrealized_pnl_usdc": pnl,
            }
            should_close = False
            if position.side is TestnetSide.LONG:
                should_close = (
                    (position.stop_loss_price is not None and mark <= position.stop_loss_price)
                    or (position.take_profit_price is not None and mark >= position.take_profit_price)
                )
            else:
                should_close = (
                    (position.stop_loss_price is not None and mark >= position.stop_loss_price)
                    or (position.take_profit_price is not None and mark <= position.take_profit_price)
                )
            if should_close:
                if hasattr(self.adapter, "prices"):
                    getattr(self.adapter, "prices")[position.coin] = mark
                results.append(
                    self.close_position(
                        position.coin,
                        position.side,
                        cloid=f"exit-{position.coin.lower()}-{position.side.value}",
                        confirmed=confirmed,
                        evidence=evidence,
                    )
                )
        return results

    def _submit(self, request: TestnetOrderRequest, *, confirmed: bool) -> TestnetOrderResult:
        decision = self.guard.evaluate(  # type: ignore[union-attr]
            self.settings,
            self.adapter,
            request,
            confirmed=confirmed,
            open_positions=self.adapter.get_testnet_positions(),
        )
        if not decision.allowed:
            self.journal.write_guard_refusal(decision.reasons, evidence=request.evidence)
            return TestnetOrderResult(
                status="rejected",
                adapter=self.adapter.name,
                environment="testnet",
                request=request,
                reasons=decision.reasons,
            )

        last_result: TestnetOrderResult | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = self.adapter.place_testnet_order(request)
                self.journal.write_result(result)
                return result
            except Exception as exc:  # noqa: BLE001 - journal testnet adapter failures.
                last_result = TestnetOrderResult(
                    status="rejected",
                    adapter=self.adapter.name,
                    environment="testnet",
                    request=request,
                    reasons=[f"adapter error attempt {attempt + 1}: {exc}"],
                )
                self.journal.write_result(last_result)
                if attempt < self.max_retries:
                    sleep(self.retry_backoff_seconds * (attempt + 1))
        assert last_result is not None
        return last_result
