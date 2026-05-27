from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hyper_smart_observer.hyperliquid_client.models import PaperPortfolioSnapshot


@dataclass
class PaperPortfolio:
    starting_equity: float = 10_000.0
    cash_usdc: float = 10_000.0
    positions: dict[str, float] = field(default_factory=dict)
    trades: list[object] = field(default_factory=list)

    def apply_fill(self, coin: str, side: str, size: float, price: float, fee: float) -> None:
        notional = size * price
        if side.lower() == "buy":
            self.cash_usdc -= notional + fee
            self.positions[coin.upper()] = self.positions.get(coin.upper(), 0.0) + size
        else:
            self.cash_usdc += notional - fee
            self.positions[coin.upper()] = self.positions.get(coin.upper(), 0.0) - size

    def get_current_equity(self) -> float:
        return self.starting_equity + self.calculate_realized_pnl()

    def list_open_trades(self) -> list[object]:
        return [trade for trade in self.trades if _trade_status(trade) == "OPEN"]

    def calculate_realized_pnl(self) -> float:
        return sum(float(getattr(trade, "net_pnl", 0.0) or 0.0) for trade in self.trades)

    def calculate_unrealized_pnl(self, mark_prices: dict[str, float] | None = None) -> float:
        if not mark_prices:
            return 0.0
        unrealized = 0.0
        for trade in self.list_open_trades():
            coin = getattr(trade, "coin", "").upper()
            mark = mark_prices.get(coin)
            if mark is None:
                continue
            side = str(getattr(trade, "side", "")).upper()
            entry = float(getattr(trade, "entry_price", 0.0) or 0.0)
            size = float(getattr(trade, "size", 0.0) or 0.0)
            if side == "BUY":
                unrealized += (mark - entry) * size
            elif side == "SELL":
                unrealized += (entry - mark) * size
        return unrealized

    def calculate_total_fees(self) -> float:
        return sum(
            float(getattr(trade, "fee_entry", None) or getattr(trade, "simulated_fee", 0.0) or 0.0)
            + float(getattr(trade, "fee_exit", 0.0) or 0.0)
            for trade in self.trades
        )

    def calculate_max_drawdown(self) -> float | None:
        closed = [float(getattr(trade, "net_pnl", 0.0) or 0.0) for trade in self.trades]
        if not closed:
            return None
        equity = self.starting_equity
        peak = equity
        max_drawdown = 0.0
        for pnl in closed:
            equity += pnl
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return max_drawdown

    def snapshot(self, mark_prices: dict[str, float] | None = None) -> PaperPortfolioSnapshot:
        open_trades = len(self.list_open_trades())
        closed_trades = len(self.trades) - open_trades
        realized = self.calculate_realized_pnl()
        unrealized = self.calculate_unrealized_pnl(mark_prices)
        return PaperPortfolioSnapshot(
            timestamp=datetime.now(UTC),
            starting_equity=self.starting_equity,
            current_equity=self.starting_equity + realized + unrealized,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_fees=self.calculate_total_fees(),
            open_trades=open_trades,
            closed_trades=closed_trades,
            max_drawdown=self.calculate_max_drawdown(),
        )


def _trade_status(trade: object) -> str:
    status = getattr(trade, "status", None)
    if hasattr(status, "value"):
        return status.value
    return str(status or getattr(trade, "state", "")).upper()
