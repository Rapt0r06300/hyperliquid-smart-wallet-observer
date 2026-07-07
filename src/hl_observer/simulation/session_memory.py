"""Session-memory guards for the local paper simulation.

This module is deliberately paper-only. It never opens, closes, signs, or sends
anything. It only looks at the local simulation ledger and decides whether a new
entry should be treated more cautiously after recent losses on the same
coin+side.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


EXIT_ACTION_MARKERS = ("CLOSE", "REDUCE", "STOP", "TAKE_PROFIT", "TRAILING")


@dataclass(frozen=True, slots=True)
class SessionMemoryStats:
    coin: str
    side: str
    session_pnl_usdc: float
    realized_exit_pnl_usdc: float
    exit_count: int
    loss_count: int
    win_count: int
    recent_loss_streak: int
    recent_win_streak: int


@dataclass(frozen=True, slots=True)
class SessionMemoryDecision:
    allow_entry: bool
    reason: str
    stats: SessionMemoryStats
    required_edge_bps: float
    strong_recovery: bool
    min_consensus: int
    min_liquidity: float

    def to_log_fields(self) -> dict[str, Any]:
        fields = {
            "session_memory_allow_entry": self.allow_entry,
            "session_memory_reason": self.reason,
            "session_memory_required_edge_bps": round(self.required_edge_bps, 6),
            "session_memory_strong_recovery": self.strong_recovery,
            "session_memory_min_consensus": self.min_consensus,
            "session_memory_min_liquidity": round(self.min_liquidity, 6),
        }
        for key, value in asdict(self.stats).items():
            fields[f"session_memory_{key}"] = value
        return fields


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_local_replay(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").upper() == "LOCAL_REPLAY"


def _event_coin(row: dict[str, Any]) -> str:
    return str(row.get("coin") or "").upper()


def _event_side(row: dict[str, Any]) -> str:
    return str(row.get("leader_side") or row.get("side") or "").upper()


def _is_exit_event(row: dict[str, Any]) -> bool:
    action = str(row.get("bot_replay_action") or row.get("paper_action_type") or row.get("exit_method") or "").upper()
    return any(marker in action for marker in EXIT_ACTION_MARKERS)


def _outcome_streaks(values: list[float]) -> tuple[int, int]:
    losses = 0
    wins = 0
    for pnl in reversed(values):
        if pnl < 0:
            if wins:
                break
            losses += 1
        elif pnl > 0:
            if losses:
                break
            wins += 1
    return losses, wins


def coin_side_session_stats(
    events: Iterable[dict[str, Any]],
    *,
    coin: str,
    side: str,
) -> SessionMemoryStats:
    """Summarize local paper outcomes for one coin+side pair."""

    coin_upper = str(coin or "").upper()
    side_upper = str(side or "").upper()
    session_pnl = 0.0
    exit_pnls: list[float] = []
    for row in events:
        if not isinstance(row, dict) or not _is_local_replay(row):
            continue
        if _event_coin(row) != coin_upper or _event_side(row) != side_upper:
            continue
        pnl = _as_float(row.get("estimated_net_pnl_usdc"), 0.0)
        session_pnl += pnl
        if _is_exit_event(row):
            exit_pnls.append(pnl)
    losses = sum(1 for value in exit_pnls if value < 0)
    wins = sum(1 for value in exit_pnls if value > 0)
    loss_streak, win_streak = _outcome_streaks(exit_pnls)
    return SessionMemoryStats(
        coin=coin_upper,
        side=side_upper,
        session_pnl_usdc=round(session_pnl, 6),
        realized_exit_pnl_usdc=round(sum(exit_pnls), 6),
        exit_count=len(exit_pnls),
        loss_count=losses,
        win_count=wins,
        recent_loss_streak=loss_streak,
        recent_win_streak=win_streak,
    )


def evaluate_coin_side_session_memory(
    *,
    events: Iterable[dict[str, Any]],
    coin: str,
    side: str,
    edge_remaining_bps: float,
    min_edge_required_bps: float,
    consensus_wallets: int,
    liquidity_score: float,
    starting_equity_usdt: float = 1000.0,
    cooldown_usdc: float | None = None,
    extra_edge_after_loss_bps: float = 35.0,
    min_consensus_after_loss: int = 3,
    min_liquidity_after_loss: float = 0.55,
) -> SessionMemoryDecision:
    """Require stronger evidence after local losses on the same coin+side.

    The guard is intentionally asymmetric: a losing HYPE SHORT run does not
    block HYPE LONG or BTC SHORT. It only forces the exact losing direction to
    come back with stronger fresh evidence.
    """

    stats = coin_side_session_stats(events, coin=coin, side=side)
    cooldown = (
        max(0.20, float(starting_equity_usdt or 1000.0) * 0.00025)
        if cooldown_usdc is None
        else max(0.0, float(cooldown_usdc))
    )
    required_edge = float(min_edge_required_bps or 0.0)
    if stats.session_pnl_usdc < 0 or stats.recent_loss_streak:
        required_edge += max(0.0, float(extra_edge_after_loss_bps or 0.0))
    edge = float(edge_remaining_bps or 0.0)
    consensus = int(consensus_wallets or 0)
    liquidity = float(liquidity_score or 0.0)
    strong_recovery = (
        edge >= required_edge
        and consensus >= int(min_consensus_after_loss or 0)
        and liquidity >= float(min_liquidity_after_loss or 0.0)
    )
    if stats.recent_loss_streak >= 2 and not strong_recovery:
        return SessionMemoryDecision(
            allow_entry=False,
            reason="COIN_SIDE_RECENT_LOSS_STREAK_REQUIRES_STRONGER_EDGE",
            stats=stats,
            required_edge_bps=required_edge,
            strong_recovery=strong_recovery,
            min_consensus=int(min_consensus_after_loss or 0),
            min_liquidity=float(min_liquidity_after_loss or 0.0),
        )
    if stats.session_pnl_usdc <= -(cooldown * 4.0) and not strong_recovery:
        return SessionMemoryDecision(
            allow_entry=False,
            reason="COIN_SIDE_SESSION_LOSS_COOLDOWN",
            stats=stats,
            required_edge_bps=required_edge,
            strong_recovery=strong_recovery,
            min_consensus=int(min_consensus_after_loss or 0),
            min_liquidity=float(min_liquidity_after_loss or 0.0),
        )
    if stats.session_pnl_usdc <= -cooldown and edge < required_edge:
        return SessionMemoryDecision(
            allow_entry=False,
            reason="COIN_SIDE_SESSION_LOSS_REQUIRES_STRONGER_EDGE",
            stats=stats,
            required_edge_bps=required_edge,
            strong_recovery=strong_recovery,
            min_consensus=int(min_consensus_after_loss or 0),
            min_liquidity=float(min_liquidity_after_loss or 0.0),
        )
    return SessionMemoryDecision(
        allow_entry=True,
        reason="SESSION_MEMORY_OK",
        stats=stats,
        required_edge_bps=required_edge,
        strong_recovery=strong_recovery,
        min_consensus=int(min_consensus_after_loss or 0),
        min_liquidity=float(min_liquidity_after_loss or 0.0),
    )


__all__ = [
    "SessionMemoryDecision",
    "SessionMemoryStats",
    "coin_side_session_stats",
    "evaluate_coin_side_session_memory",
]
