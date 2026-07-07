from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from hl_observer.testnet.models import (
    TestnetAction,
    TestnetOrderRequest,
    TestnetOrderResult,
    TestnetPortfolioSnapshot,
    TestnetPositionSnapshot,
    TestnetSide,
)


class TestnetExchangeAdapter(Protocol):
    name: str
    environment: str
    base_url: str

    def connect(self) -> None: ...

    def get_market_data(self, coins: list[str] | None = None) -> dict[str, float]: ...

    def place_testnet_order(self, request: TestnetOrderRequest) -> TestnetOrderResult: ...

    def cancel_testnet_order(self, cloid: str) -> dict[str, str]: ...

    def get_testnet_open_orders(self) -> list[dict[str, object]]: ...

    def get_testnet_positions(self) -> list[TestnetPositionSnapshot]: ...

    def get_testnet_fills(self) -> list[dict[str, object]]: ...

    def get_testnet_pnl(self) -> TestnetPortfolioSnapshot: ...

    def close_testnet_position(self, coin: str, side: TestnetSide, *, cloid: str) -> TestnetOrderResult: ...


@dataclass(slots=True)
class FakeTestnetExchangeAdapter:
    """Deterministic fake testnet adapter for tests, CLI dry-confirmed runs and dashboards."""

    prices: dict[str, float] = field(default_factory=lambda: {"BTC": 60_000.0, "ETH": 3_000.0, "SOL": 150.0, "HYPE": 40.0})
    starting_equity_usdc: float = 1_000.0
    name: str = "fake_hyperliquid_testnet"
    environment: str = "testnet"
    base_url: str = "https://api.hyperliquid-testnet.xyz/fake-adapter"
    connected: bool = False
    orders: list[dict[str, object]] = field(default_factory=list)
    fills: list[dict[str, object]] = field(default_factory=list)
    realized_pnl_usdc: float = 0.0
    _positions: dict[tuple[str, TestnetSide], TestnetPositionSnapshot] = field(default_factory=dict)

    def connect(self) -> None:
        self.connected = True

    def get_market_data(self, coins: list[str] | None = None) -> dict[str, float]:
        if coins is None:
            return dict(self.prices)
        return {coin.upper(): self.prices.get(coin.upper(), 0.0) for coin in coins}

    def place_testnet_order(self, request: TestnetOrderRequest) -> TestnetOrderResult:
        self.connect()
        coin = request.normalized_coin()
        mark = self.prices.get(coin, request.limit_price)
        if request.action is TestnetAction.CLOSE:
            result = self.close_testnet_position(coin, request.side, cloid=request.cloid)
        else:
            size = request.requested_size()
            if size <= 0 or request.notional_usdc <= 0:
                return TestnetOrderResult(
                    status="rejected",
                    adapter=self.name,
                    environment="testnet",
                    request=request,
                    reasons=["invalid non-positive notional or size"],
                )
            if request.action is TestnetAction.OPEN:
                result = self._open(request, coin, mark, size)
            elif request.action is TestnetAction.REDUCE:
                result = self._reduce(request, coin, mark, size)
            else:
                result = TestnetOrderResult(
                    status="rejected",
                    adapter=self.name,
                    environment="testnet",
                    request=request,
                    reasons=["unsupported testnet action"],
                )
        self.orders.append({"cloid": request.cloid, "status": result.status, "request": request.to_dict()})
        if result.accepted:
            self.fills.append(
                {
                    "fill_id": result.external_ref,
                    "cloid": request.cloid,
                    "coin": coin,
                    "side": request.side.value,
                    "action": request.action.value,
                    "price": result.average_price,
                    "size": result.filled_size,
                    "realized_pnl_usdc": result.realized_pnl_usdc,
                }
            )
        return result

    def cancel_testnet_order(self, cloid: str) -> dict[str, str]:
        return {"status": "canceled_or_not_found", "cloid": cloid, "adapter": self.name}

    def get_testnet_open_orders(self) -> list[dict[str, object]]:
        return [order for order in self.orders if order.get("status") == "open"]

    def get_testnet_positions(self) -> list[TestnetPositionSnapshot]:
        return list(self._positions.values())

    def get_testnet_fills(self) -> list[dict[str, object]]:
        return list(self.fills)

    def get_testnet_pnl(self) -> TestnetPortfolioSnapshot:
        unrealized = sum(position.unrealized_pnl_usdc for position in self._positions.values())
        return TestnetPortfolioSnapshot(
            adapter=self.name,
            environment="testnet",
            realized_pnl_usdc=self.realized_pnl_usdc,
            unrealized_pnl_usdc=unrealized,
            equity_usdc=self.starting_equity_usdc + self.realized_pnl_usdc + unrealized,
            open_positions=self.get_testnet_positions(),
        )

    def close_testnet_position(self, coin: str, side: TestnetSide, *, cloid: str) -> TestnetOrderResult:
        key = (coin.upper(), side)
        existing = self._positions.pop(key, None)
        request = TestnetOrderRequest(
            cloid=cloid,
            action=TestnetAction.CLOSE,
            coin=coin.upper(),
            side=side,
            notional_usdc=0.0,
            limit_price=self.prices.get(coin.upper(), existing.mark_price if existing else 0.0),
            reduce_only=True,
        )
        if existing is None:
            return TestnetOrderResult(
                status="rejected",
                adapter=self.name,
                environment="testnet",
                request=request,
                reasons=["no matching testnet position"],
            )
        close_mark = self.prices.get(coin.upper(), existing.mark_price)
        realized = self._pnl_for(existing.side, existing.entry_price, close_mark, existing.size)
        self.realized_pnl_usdc += realized
        return TestnetOrderResult(
            status="accepted",
            adapter=self.name,
            environment="testnet",
            request=request,
            average_price=close_mark,
            filled_size=existing.size,
            realized_pnl_usdc=realized,
            external_ref=f"fake-fill-{uuid4().hex[:12]}",
        )

    def _open(self, request: TestnetOrderRequest, coin: str, mark: float, size: float) -> TestnetOrderResult:
        key = (coin, request.side)
        existing = self._positions.get(key)
        if existing:
            total_size = existing.size + size
            avg_entry = ((existing.entry_price * existing.size) + (mark * size)) / total_size
            position = self._position(
                coin,
                request.side,
                total_size,
                avg_entry,
                mark,
                stop_loss_price=request.stop_loss_price or existing.stop_loss_price,
                take_profit_price=request.take_profit_price or existing.take_profit_price,
                trailing_stop_bps=request.trailing_stop_bps or existing.trailing_stop_bps,
            )
        else:
            position = self._position(
                coin,
                request.side,
                size,
                mark,
                mark,
                stop_loss_price=request.stop_loss_price,
                take_profit_price=request.take_profit_price,
                trailing_stop_bps=request.trailing_stop_bps,
            )
        self._positions[key] = position
        return TestnetOrderResult(
            status="accepted",
            adapter=self.name,
            environment="testnet",
            request=request,
            average_price=mark,
            filled_size=size,
            unrealized_pnl_usdc=position.unrealized_pnl_usdc,
            external_ref=f"fake-fill-{uuid4().hex[:12]}",
        )

    def _reduce(self, request: TestnetOrderRequest, coin: str, mark: float, size: float) -> TestnetOrderResult:
        key = (coin, request.side)
        existing = self._positions.get(key)
        if existing is None:
            return TestnetOrderResult(
                status="rejected",
                adapter=self.name,
                environment="testnet",
                request=request,
                reasons=["no matching testnet position"],
            )
        reduced_size = min(size, existing.size)
        realized = self._pnl_for(existing.side, existing.entry_price, mark, reduced_size)
        self.realized_pnl_usdc += realized
        remaining = existing.size - reduced_size
        if remaining <= 1e-12:
            self._positions.pop(key, None)
        else:
            self._positions[key] = self._position(
                coin,
                request.side,
                remaining,
                existing.entry_price,
                mark,
                stop_loss_price=existing.stop_loss_price,
                take_profit_price=existing.take_profit_price,
                trailing_stop_bps=existing.trailing_stop_bps,
            )
        return TestnetOrderResult(
            status="accepted",
            adapter=self.name,
            environment="testnet",
            request=request,
            average_price=mark,
            filled_size=reduced_size,
            realized_pnl_usdc=realized,
            external_ref=f"fake-fill-{uuid4().hex[:12]}",
        )

    def _position(
        self,
        coin: str,
        side: TestnetSide,
        size: float,
        entry: float,
        mark: float,
        *,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        trailing_stop_bps: float | None = None,
    ) -> TestnetPositionSnapshot:
        return TestnetPositionSnapshot(
            coin=coin,
            side=side,
            size=size,
            entry_price=entry,
            mark_price=mark,
            notional_usdc=size * mark,
            unrealized_pnl_usdc=self._pnl_for(side, entry, mark, size),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_bps=trailing_stop_bps,
        )

    @staticmethod
    def _pnl_for(side: TestnetSide, entry: float, mark: float, size: float) -> float:
        if side is TestnetSide.LONG:
            return (mark - entry) * size
        return (entry - mark) * size


@dataclass(slots=True)
class HyperliquidTestnetAdapter:
    """Hyperliquid testnet adapter shell.

    Market reads are supported through injected read-only clients. External testnet order
    submission intentionally requires an explicit signer transport in a future reviewed sprint.
    """

    base_url: str = "https://api.hyperliquid-testnet.xyz"
    name: str = "hyperliquid_testnet_locked"
    environment: str = "testnet"
    status: str = "READY_BUT_LOCKED_SIGNATURE_REQUIRED"
    market_prices: dict[str, float] = field(default_factory=dict)
    connected: bool = False

    def connect(self) -> None:
        if "testnet" not in self.base_url.lower():
            raise RuntimeError("Hyperliquid testnet adapter refused non-testnet URL")
        self.connected = True

    def get_market_data(self, coins: list[str] | None = None) -> dict[str, float]:
        self.connect()
        if coins is None:
            return dict(self.market_prices)
        return {coin.upper(): self.market_prices.get(coin.upper(), 0.0) for coin in coins}

    def place_testnet_order(self, request: TestnetOrderRequest) -> TestnetOrderResult:
        return self._locked_result(request, self.status)

    def cancel_testnet_order(self, cloid: str) -> dict[str, str]:
        return {"status": "rejected", "cloid": cloid, "reason": self.status}

    def get_testnet_open_orders(self) -> list[dict[str, object]]:
        return []

    def get_testnet_positions(self) -> list[TestnetPositionSnapshot]:
        return []

    def get_testnet_fills(self) -> list[dict[str, object]]:
        return []

    def get_testnet_pnl(self) -> TestnetPortfolioSnapshot:
        return TestnetPortfolioSnapshot(
            adapter=self.name,
            environment="testnet",
            realized_pnl_usdc=0.0,
            unrealized_pnl_usdc=0.0,
            equity_usdc=0.0,
            open_positions=[],
        )

    def close_testnet_position(self, coin: str, side: TestnetSide, *, cloid: str) -> TestnetOrderResult:
        request = TestnetOrderRequest(
            cloid=cloid,
            action=TestnetAction.CLOSE,
            coin=coin,
            side=side,
            notional_usdc=0.0,
            limit_price=0.0,
            reduce_only=True,
        )
        return self._locked_result(request, self.status)

    def _locked_result(self, request: TestnetOrderRequest, reason: str) -> TestnetOrderResult:
        self.connect()
        return TestnetOrderResult(
            status="rejected",
            adapter=self.name,
            environment="testnet",
            request=request,
            reasons=[reason],
        )
