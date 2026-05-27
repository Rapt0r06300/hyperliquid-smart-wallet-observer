from __future__ import annotations

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.wallet_following_simulator import simulate_wallet_following


class ReplayEngine:
    def replay_closed_pnl(self, wallet_address: str, closed_pnls: list[float]) -> BacktestReport:
        return simulate_wallet_following(wallet_address, closed_pnls)
