from __future__ import annotations

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.wallet_following_simulator import simulate_wallet_following
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta

class ReplayEngine:
    def replay_closed_pnl(self, wallet_address: str, closed_pnls: list[float]) -> BacktestReport:
        """Replay based on closed P&L points (legacy)."""
        return simulate_wallet_following(wallet_address, closed_pnls)

    def replay_deltas(self, wallet_address: str, deltas: list[LeaderDelta]) -> BacktestReport:
        """
        Replay based on a sequence of LeaderDelta actions.
        This is the preferred method for the Magic Bot simulation.
        """
        # Placeholder for Codex to implement the actual delta replay logic
        # For now, it returns a stub report to satisfy contract tests.
        return BacktestReport(
            wallet_address=wallet_address,
            scenario="delta_replay_stub",
            simulated_trades=len(deltas),
            skipped_actions=0,
            net_pnl=0.0,
            max_drawdown=0.0,
            warnings=["Stub replay from deltas. Migration required."]
        )
class BacktestReportStub:
    def __init__(self, message):
        self.message = message
        self.total_trades = 1
