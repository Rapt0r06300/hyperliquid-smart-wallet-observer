"""Session-level circuit breaker — inspired by ClaudePolymarketTrader.

The viral bots pause trading when drawdown/streak exceeds thresholds.
This prevents catastrophic losses from correlated bad signals.

Pattern from ClaudePolymarketTrader:
- Max daily loss: -5% of equity → pause 1 hour
- Max losing streak: 3 consecutive losses → pause 30 min
- Max drawdown from peak: -8% → pause until manual reset
- Recovery mode: reduced position sizing after pause

SAFETY: simulation paper uniquement. Aucun ordre réel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass


class CircuitState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"        # Approaching limits, reduce sizing
    PAUSED = "PAUSED"          # Temporarily paused
    HALTED = "HALTED"          # Halted until manual reset
    RECOVERY = "RECOVERY"      # Post-pause, reduced sizing


@dataclass(slots=True)
class CircuitBreakerConfig:
    """Thresholds for circuit breaker activation."""

    # Session drawdown limits (from peak equity)
    caution_drawdown_pct: float = 3.0     # Enter CAUTION, reduce sizing
    pause_drawdown_pct: float = 5.0       # Pause for cooldown_minutes
    halt_drawdown_pct: float = 10.0       # Halt until manual reset

    # Losing streak limits
    caution_losing_streak: int = 2        # Enter CAUTION
    pause_losing_streak: int = 4          # Pause for cooldown_minutes
    halt_losing_streak: int = 7           # Halt

    # Cooldown
    cooldown_minutes: float = 30.0        # How long PAUSED lasts

    # Recovery mode: sizing multiplier after returning from pause
    recovery_sizing_multiplier: float = 0.5
    recovery_trades_before_normal: int = 3  # N winning trades to exit RECOVERY

    # Daily limits
    max_trades_per_hour: int = 10
    max_trades_per_day: int = 50

    # PnL velocity: if losing X bps in Y minutes, pause
    rapid_loss_bps: float = 50.0
    rapid_loss_window_minutes: float = 15.0


@dataclass(slots=True)
class CircuitBreakerState:
    """Current state of the circuit breaker."""

    state: CircuitState = CircuitState.NORMAL
    peak_equity_usdt: float = 1000.0
    current_equity_usdt: float = 1000.0
    session_pnl_usdt: float = 0.0
    consecutive_losses: int = 0
    consecutive_wins_in_recovery: int = 0
    trades_this_hour: int = 0
    trades_this_day: int = 0
    last_trade_timestamp: float = 0.0
    paused_at: float = 0.0
    recent_pnl_events: list[tuple[float, float]] = field(default_factory=list)
    # (timestamp, pnl_bps)
    sizing_multiplier: float = 1.0
    reasons: list[str] = field(default_factory=list)


def evaluate_circuit_breaker(
    state: CircuitBreakerState,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerState:
    """Evaluate and update circuit breaker state.

    Called before each new paper trade decision.
    Returns updated state with sizing_multiplier and reasons.

    PAPER SIMULATION ONLY.
    """
    cfg = config or CircuitBreakerConfig()
    now = time.time()
    reasons: list[str] = []

    # --- Check if pause has expired ---
    if state.state == CircuitState.PAUSED:
        elapsed_minutes = (now - state.paused_at) / 60.0
        if elapsed_minutes >= cfg.cooldown_minutes:
            state.state = CircuitState.RECOVERY
            state.consecutive_wins_in_recovery = 0
            reasons.append("COOLDOWN_EXPIRED_ENTERING_RECOVERY")
        else:
            remaining = cfg.cooldown_minutes - elapsed_minutes
            reasons.append(f"PAUSED_REMAINING_{remaining:.0f}min")
            state.sizing_multiplier = 0.0
            state.reasons = reasons
            return state

    # --- Check if HALTED (requires manual reset) ---
    if state.state == CircuitState.HALTED:
        reasons.append("HALTED_MANUAL_RESET_REQUIRED")
        state.sizing_multiplier = 0.0
        state.reasons = reasons
        return state

    # --- Compute drawdown from peak ---
    if state.current_equity_usdt > state.peak_equity_usdt:
        state.peak_equity_usdt = state.current_equity_usdt

    drawdown_pct = 0.0
    if state.peak_equity_usdt > 0:
        drawdown_pct = (state.peak_equity_usdt - state.current_equity_usdt) / state.peak_equity_usdt * 100.0

    # --- Check halt conditions ---
    if drawdown_pct >= cfg.halt_drawdown_pct:
        state.state = CircuitState.HALTED
        state.sizing_multiplier = 0.0
        reasons.append(f"HALT_DRAWDOWN_{drawdown_pct:.1f}pct")
        state.reasons = reasons
        return state

    if state.consecutive_losses >= cfg.halt_losing_streak:
        state.state = CircuitState.HALTED
        state.sizing_multiplier = 0.0
        reasons.append(f"HALT_LOSING_STREAK_{state.consecutive_losses}")
        state.reasons = reasons
        return state

    # --- Check pause conditions ---
    if drawdown_pct >= cfg.pause_drawdown_pct:
        state.state = CircuitState.PAUSED
        state.paused_at = now
        state.sizing_multiplier = 0.0
        reasons.append(f"PAUSE_DRAWDOWN_{drawdown_pct:.1f}pct")
        state.reasons = reasons
        return state

    if state.consecutive_losses >= cfg.pause_losing_streak:
        state.state = CircuitState.PAUSED
        state.paused_at = now
        state.sizing_multiplier = 0.0
        reasons.append(f"PAUSE_LOSING_STREAK_{state.consecutive_losses}")
        state.reasons = reasons
        return state

    # --- Check rapid loss velocity ---
    cutoff = now - cfg.rapid_loss_window_minutes * 60.0
    recent = [pnl for ts, pnl in state.recent_pnl_events if ts >= cutoff]
    if recent:
        total_recent_loss_bps = sum(min(0, p) for p in recent)
        if abs(total_recent_loss_bps) >= cfg.rapid_loss_bps:
            state.state = CircuitState.PAUSED
            state.paused_at = now
            state.sizing_multiplier = 0.0
            reasons.append(f"PAUSE_RAPID_LOSS_{abs(total_recent_loss_bps):.0f}bps_in_{cfg.rapid_loss_window_minutes:.0f}min")
            state.reasons = reasons
            return state

    # --- Check rate limits ---
    if state.trades_this_hour >= cfg.max_trades_per_hour:
        reasons.append("RATE_LIMIT_HOURLY")
        state.sizing_multiplier = 0.0
        state.reasons = reasons
        return state

    if state.trades_this_day >= cfg.max_trades_per_day:
        reasons.append("RATE_LIMIT_DAILY")
        state.sizing_multiplier = 0.0
        state.reasons = reasons
        return state

    # --- Determine sizing multiplier ---
    if state.state == CircuitState.RECOVERY:
        if state.consecutive_wins_in_recovery >= cfg.recovery_trades_before_normal:
            state.state = CircuitState.NORMAL
            state.sizing_multiplier = 1.0
            reasons.append("RECOVERY_COMPLETE_BACK_TO_NORMAL")
        else:
            state.sizing_multiplier = cfg.recovery_sizing_multiplier
            reasons.append(f"RECOVERY_MODE_SIZING_{cfg.recovery_sizing_multiplier:.0%}")

    elif drawdown_pct >= cfg.caution_drawdown_pct or state.consecutive_losses >= cfg.caution_losing_streak:
        state.state = CircuitState.CAUTION
        state.sizing_multiplier = 0.7
        if drawdown_pct >= cfg.caution_drawdown_pct:
            reasons.append(f"CAUTION_DRAWDOWN_{drawdown_pct:.1f}pct")
        if state.consecutive_losses >= cfg.caution_losing_streak:
            reasons.append(f"CAUTION_STREAK_{state.consecutive_losses}")
    else:
        state.state = CircuitState.NORMAL
        state.sizing_multiplier = 1.0

    state.reasons = reasons
    return state


def record_trade_result(
    state: CircuitBreakerState,
    pnl_bps: float,
    pnl_usdt: float,
) -> CircuitBreakerState:
    """Record a closed trade result for circuit breaker tracking."""
    now = time.time()

    state.session_pnl_usdt += pnl_usdt
    state.current_equity_usdt += pnl_usdt
    state.recent_pnl_events.append((now, pnl_bps))

    # Trim old events (keep last hour)
    cutoff = now - 3600.0
    state.recent_pnl_events = [
        (ts, pnl) for ts, pnl in state.recent_pnl_events if ts >= cutoff
    ]

    if pnl_usdt >= 0:
        state.consecutive_losses = 0
        if state.state == CircuitState.RECOVERY:
            state.consecutive_wins_in_recovery += 1
    else:
        state.consecutive_losses += 1
        state.consecutive_wins_in_recovery = 0

    state.trades_this_hour += 1
    state.trades_this_day += 1
    state.last_trade_timestamp = now

    return state


def reset_circuit_breaker(state: CircuitBreakerState) -> CircuitBreakerState:
    """Manual reset from HALTED state."""
    state.state = CircuitState.RECOVERY
    state.consecutive_losses = 0
    state.consecutive_wins_in_recovery = 0
    state.sizing_multiplier = 0.5
    state.reasons = ["MANUAL_RESET_ENTERING_RECOVERY"]
    return state
