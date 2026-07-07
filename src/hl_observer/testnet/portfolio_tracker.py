from __future__ import annotations

from dataclasses import dataclass

from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.models import TestnetPortfolioSnapshot


@dataclass(slots=True)
class TestnetPortfolioTracker:
    adapter: TestnetExchangeAdapter

    def snapshot(self) -> TestnetPortfolioSnapshot:
        return self.adapter.get_testnet_pnl()

    def dashboard_payload(self) -> dict[str, object]:
        portfolio = self.snapshot()
        return {
            "mode": "TESTNET_ONLY",
            "adapter": portfolio.adapter,
            "environment": portfolio.environment,
            "equity_usdc": portfolio.equity_usdc,
            "realized_pnl_usdc": portfolio.realized_pnl_usdc,
            "unrealized_pnl_usdc": portfolio.unrealized_pnl_usdc,
            "open_positions": [position.to_dict() for position in portfolio.open_positions],
            "open_orders": self.adapter.get_testnet_open_orders(),
            "fills": self.adapter.get_testnet_fills(),
            "warning": "Testnet liquidity can differ from mainnet; use for controlled execution tests only.",
        }
