from __future__ import annotations

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.wallet_following_simulator import (
    simulate_wallet_following,
    simulate_wallet_following_deltas,
)
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta


class ReplayEngine:
    def replay_closed_pnl(self, wallet_address: str, closed_pnls: list[float]) -> BacktestReport:
        return simulate_wallet_following(wallet_address, closed_pnls)

    def replay_deltas(self, wallet_address: str, deltas: list[LeaderDelta]) -> BacktestReport:
        return simulate_wallet_following_deltas(wallet_address, deltas)
