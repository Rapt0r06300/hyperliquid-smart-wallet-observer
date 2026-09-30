"""Per-leader PnL attribution — inspired by LearnWithMeAI's Job C.

The viral bots track PnL per leader wallet to:
1. Identify which leaders are actually profitable to copy
2. Auto-eject leaders whose copy-PnL goes negative over N trades
3. Promote leaders whose signals consistently generate paper profit

This module provides session-level tracking. It does NOT persist across
restarts (stateless design for simulation safety).

SAFETY: simulation paper uniquement. Aucun ordre réel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class LeaderTradeRecord:
    """One closed paper trade attributed to a leader."""

    leader_address: str
    coin: str
    side: str
    entry_price: float
    exit_price: float
    notional_usdt: float
    pnl_usdt: float
    pnl_bps: float
    entry_timestamp: float
    exit_timestamp: float
    hold_duration_ms: int
    signal_age_at_entry_ms: int


@dataclass(slots=True)
class LeaderPerformance:
    """Aggregated performance for one leader in this session."""

    leader_address: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl_usdt: float = 0.0
    total_pnl_bps: float = 0.0
    max_single_win_usdt: float = 0.0
    max_single_loss_usdt: float = 0.0
    avg_hold_duration_ms: float = 0.0
    avg_signal_age_ms: float = 0.0
    consecutive_losses: int = 0
    last_trade_timestamp: float = 0.0

    # Derived metrics
    @property
    def win_rate(self) -> float:
        return self.winning_trades / max(1, self.total_trades)

    @property
    def avg_pnl_per_trade_usdt(self) -> float:
        return self.total_pnl_usdt / max(1, self.total_trades)

    @property
    def avg_pnl_per_trade_bps(self) -> float:
        return self.total_pnl_bps / max(1, self.total_trades)

    @property
    def profit_factor(self) -> float:
        """Gross wins / gross losses."""
        if self.max_single_loss_usdt == 0:
            return float("inf") if self.total_pnl_usdt > 0 else 0.0
        total_losses = abs(sum(
            r.pnl_usdt for r in self._trades if r.pnl_usdt < 0
        )) if hasattr(self, "_trades") else abs(self.max_single_loss_usdt)
        total_wins = sum(
            r.pnl_usdt for r in self._trades if r.pnl_usdt > 0
        ) if hasattr(self, "_trades") else self.max_single_win_usdt
        return total_wins / max(0.01, total_losses)

    @property
    def status(self) -> str:
        """Leader status based on copy performance."""
        if self.total_trades < 3:
            return "EVALUATING"
        if self.total_pnl_usdt > 0 and self.win_rate >= 0.50:
            return "PROFITABLE"
        if self.consecutive_losses >= 4:
            return "EJECT_STREAK"
        if self.total_trades >= 5 and self.total_pnl_usdt < 0:
            return "EJECT_NEGATIVE_PNL"
        if self.win_rate < 0.35:
            return "EJECT_LOW_WIN_RATE"
        return "MARGINAL"


@dataclass
class LeaderPnLTracker:
    """Session-level tracker for per-leader copy PnL.

    Design inspired by:
    - LearnWithMeAI: Daily shortlist recomputation based on copy performance
    - Polyphemus: Per-signal P&L tracking with attribution
    - ClaudePolymarketTrader: Losing streak detection per strategy

    PAPER SIMULATION ONLY.
    """

    _leaders: dict[str, LeaderPerformance] = field(default_factory=dict)
    _trades: list[LeaderTradeRecord] = field(default_factory=list)

    # Config for auto-rotation
    min_trades_before_eject: int = 3
    max_consecutive_losses: int = 4
    min_win_rate_threshold: float = 0.35
    eject_after_n_losing_trades: int = 5

    def record_trade(self, trade: LeaderTradeRecord) -> LeaderPerformance:
        """Record a completed paper trade and update leader stats."""
        addr = trade.leader_address.lower()
        self._trades.append(trade)

        if addr not in self._leaders:
            self._leaders[addr] = LeaderPerformance(leader_address=addr)

        perf = self._leaders[addr]
        perf.total_trades += 1
        perf.total_pnl_usdt += trade.pnl_usdt
        perf.total_pnl_bps += trade.pnl_bps
        perf.last_trade_timestamp = trade.exit_timestamp

        if trade.pnl_usdt > 0:
            perf.winning_trades += 1
            perf.consecutive_losses = 0
            perf.max_single_win_usdt = max(perf.max_single_win_usdt, trade.pnl_usdt)
        else:
            perf.losing_trades += 1
            perf.consecutive_losses += 1
            perf.max_single_loss_usdt = min(perf.max_single_loss_usdt, trade.pnl_usdt)

        # Update running averages
        n = perf.total_trades
        perf.avg_hold_duration_ms = (
            perf.avg_hold_duration_ms * (n - 1) + trade.hold_duration_ms
        ) / n
        perf.avg_signal_age_ms = (
            perf.avg_signal_age_ms * (n - 1) + trade.signal_age_at_entry_ms
        ) / n

        return perf

    def get_leader_performance(self, leader_address: str) -> LeaderPerformance | None:
        """Get performance for a specific leader."""
        return self._leaders.get(leader_address.lower())

    def get_all_performances(self) -> list[LeaderPerformance]:
        """Get all leader performances, sorted by PnL descending."""
        return sorted(
            self._leaders.values(),
            key=lambda p: p.total_pnl_usdt,
            reverse=True,
        )

    def should_eject_leader(self, leader_address: str) -> tuple[bool, str]:
        """Check if a leader should be ejected based on copy performance.

        Returns (should_eject, reason).
        """
        perf = self._leaders.get(leader_address.lower())
        if perf is None:
            return False, "no_data"

        if perf.total_trades < self.min_trades_before_eject:
            return False, "evaluating"

        if perf.consecutive_losses >= self.max_consecutive_losses:
            return True, f"consecutive_losses_{perf.consecutive_losses}"

        if perf.total_trades >= self.eject_after_n_losing_trades and perf.total_pnl_usdt < 0:
            return True, f"negative_pnl_after_{perf.total_trades}_trades"

        if perf.total_trades >= 5 and perf.win_rate < self.min_win_rate_threshold:
            return True, f"low_win_rate_{perf.win_rate:.0%}"

        return False, "ok"

    def get_leaders_to_eject(self) -> list[tuple[str, str]]:
        """Get all leaders that should be ejected.

        Returns list of (address, reason) tuples.
        """
        result = []
        for addr, perf in self._leaders.items():
            should_eject, reason = self.should_eject_leader(addr)
            if should_eject:
                result.append((addr, reason))
        return result

    def get_profitable_leaders(self) -> list[str]:
        """Get addresses of profitable leaders (for shortlist reinforcement)."""
        return [
            addr for addr, perf in self._leaders.items()
            if perf.status == "PROFITABLE"
        ]

    def get_session_summary(self) -> dict:
        """Summary stats for dashboard / reporting (Job C pattern)."""
        all_perfs = self.get_all_performances()
        profitable = [p for p in all_perfs if p.total_pnl_usdt > 0]
        losing = [p for p in all_perfs if p.total_pnl_usdt < 0]

        return {
            "total_leaders_tracked": len(all_perfs),
            "profitable_leaders": len(profitable),
            "losing_leaders": len(losing),
            "total_session_pnl_usdt": round(sum(p.total_pnl_usdt for p in all_perfs), 2),
            "total_trades": sum(p.total_trades for p in all_perfs),
            "overall_win_rate": (
                sum(p.winning_trades for p in all_perfs) /
                max(1, sum(p.total_trades for p in all_perfs))
            ),
            "best_leader": all_perfs[0].leader_address if all_perfs else None,
            "best_leader_pnl": all_perfs[0].total_pnl_usdt if all_perfs else 0.0,
            "worst_leader": all_perfs[-1].leader_address if all_perfs else None,
            "worst_leader_pnl": all_perfs[-1].total_pnl_usdt if all_perfs else 0.0,
            "leaders_to_eject": len(self.get_leaders_to_eject()),
        }
