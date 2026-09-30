"""Circuit breaker — rapid-fire / anomaly halt (S7 — V9, Harrier A4).

Distinct from the other two risk layers, on purpose:
  * ``loss_halts``  -> cumulative % halts (daily 5% / monthly 15% / drawdown 25%).
  * ``exec_gates``  -> per-decision liquidity / spread / staleness veto.
  * ``circuit_breaker`` (this module) -> *burst* protection: trip when too many
    trades, too many consecutive losses, or too many big losses happen inside a
    short rolling window. Catches a run-away loop or a regime where the bot would
    otherwise machine-gun losing paper entries.

A trip is *armed by a recorded trade* and arms a cooldown; read-only checks
(``evaluate`` / ``allow_entry``) only reflect the cooldown and never extend it.
When the cooldown elapses the breaker forgives the trades that armed it, so it
does not re-trip forever on the same stale evidence. Deterministic: the caller
passes timestamps (seconds) and paper PnL — no wall clock, trivially testable.

SAFETY: this only ever blocks new *paper* entries. It never places, cancels, or
signs anything real. A signal is never an order; a paper trade is never an order.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    window_sec: float = 300.0
    max_trades_in_window: int = 12
    max_consecutive_losses: int = 4
    big_loss_usdc: float = 5.0
    max_big_losses_in_window: int = 3
    cooldown_sec: float = 1_800.0

    def __post_init__(self) -> None:  # deny-by-default friendly
        if self.window_sec <= 0:
            raise ValueError("window_sec must be > 0")
        if self.cooldown_sec < 0:
            raise ValueError("cooldown_sec must be >= 0")


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    timestamp_sec: float
    pnl_usdc: float
    notional_usdc: float = 0.0

    @property
    def is_loss(self) -> bool:
        return self.pnl_usdc < 0.0


@dataclass(frozen=True, slots=True)
class BreakerDecision:
    tripped: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    cooldown_until_sec: float | None = None
    trades_in_window: int = 0
    consecutive_losses: int = 0
    big_losses_in_window: int = 0

    @property
    def entry_allowed(self) -> bool:
        return not self.tripped


class CircuitBreaker:
    """Stateful, in-memory burst breaker for the paper simulation."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._cfg = config or CircuitBreakerConfig()
        self._trades: deque[TradeOutcome] = deque()
        self._cooldown_until: float | None = None

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._cfg

    def reset(self) -> None:
        self._trades.clear()
        self._cooldown_until = None

    def _refresh(self, now_sec: float) -> None:
        # Forgive the trades that armed an expired cooldown, then drop trades
        # that have fallen out of the rolling window.
        if self._cooldown_until is not None and now_sec >= self._cooldown_until:
            forgive_before = self._cooldown_until
            self._trades = deque(o for o in self._trades if o.timestamp_sec >= forgive_before)
            self._cooldown_until = None
        cutoff = now_sec - self._cfg.window_sec
        while self._trades and self._trades[0].timestamp_sec < cutoff:
            self._trades.popleft()

    def _consecutive_losses(self) -> int:
        streak = 0
        for outcome in reversed(self._trades):
            if outcome.is_loss:
                streak += 1
            else:
                break
        return streak

    def _condition_reasons(self) -> tuple[list[str], int, int, int]:
        cfg = self._cfg
        n = len(self._trades)
        consec = self._consecutive_losses()
        big = sum(1 for o in self._trades if o.is_loss and abs(o.pnl_usdc) >= cfg.big_loss_usdc)
        reasons: list[str] = []
        if n > cfg.max_trades_in_window:
            reasons.append("TRADE_RATE_TOO_HIGH")
        if consec >= cfg.max_consecutive_losses:
            reasons.append("CONSECUTIVE_LOSSES")
        if big >= cfg.max_big_losses_in_window:
            reasons.append("BIG_LOSS_CLUSTER")
        return reasons, n, consec, big

    def record(self, outcome: TradeOutcome) -> BreakerDecision:
        """Record a closed paper trade and (re)assess the breaker."""
        now = outcome.timestamp_sec
        self._refresh(now)
        self._trades.append(outcome)
        reasons, n, consec, big = self._condition_reasons()
        if reasons:
            self._cooldown_until = now + self._cfg.cooldown_sec
        cooling = self._cooldown_until is not None and now < self._cooldown_until
        if cooling and not reasons:
            reasons = [*reasons, "COOLDOWN_ACTIVE"]
        tripped = bool(reasons) or cooling
        return BreakerDecision(
            tripped=tripped,
            reasons=tuple(reasons),
            cooldown_until_sec=self._cooldown_until if tripped else None,
            trades_in_window=n,
            consecutive_losses=consec,
            big_losses_in_window=big,
        )

    def evaluate(self, now_sec: float) -> BreakerDecision:
        """Read-only snapshot. Reflects the cooldown; never arms or extends it."""
        self._refresh(now_sec)
        _, n, consec, big = self._condition_reasons()
        cooling = self._cooldown_until is not None and now_sec < self._cooldown_until
        return BreakerDecision(
            tripped=cooling,
            reasons=("COOLDOWN_ACTIVE",) if cooling else (),
            cooldown_until_sec=self._cooldown_until if cooling else None,
            trades_in_window=n,
            consecutive_losses=consec,
            big_losses_in_window=big,
        )

    def allow_entry(self, now_sec: float) -> bool:
        """True if a new *paper* entry is currently permitted."""
        return self.evaluate(now_sec).entry_allowed


__all__ = [
    "CircuitBreakerConfig",
    "TradeOutcome",
    "BreakerDecision",
    "CircuitBreaker",
]
