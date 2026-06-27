"""Temporal entry eligibility + explicit signal shape (S6/S8 — V9, Composio A2/A3).

Two complementary V9 ideas, kept pure and deterministic:

  * **Temporal eligibility gate** (A2): enforce a cooldown between paper entries on
    the *same coin*, and a cap on entries per coin inside a rolling window. This is
    the anti-over-trade / anti-duplicate-entry rule that supports the "fewer but
    cleaner" thesis — it stops the bot re-entering the same coin every few seconds.
  * **Explicit signal shape** (A3): a small, typed description of a signal
    (action, edge, spread, status) so a decision is legible and auditable rather
    than an opaque float.

The caller passes timestamps (seconds) and the last-entry time per coin; the
module returns an eligibility verdict + reason. SAFETY: pure, paper-only — being
"eligible" only means a paper entry is *permitted*, never that one is placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# explicit statuses for the signal shape
STATUS_OK = "OK"
STATUS_STALE = "STALE"
STATUS_LOW_EDGE = "LOW_EDGE"
STATUS_WIDE_SPREAD = "WIDE_SPREAD"


@dataclass(frozen=True, slots=True)
class EligibilityConfig:
    cooldown_sec: float = 60.0
    """Minimum seconds between two paper entries on the same coin."""
    max_entries_per_window: int = 3
    """Max entries on the same coin inside ``window_sec``."""
    window_sec: float = 900.0


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reason: str
    seconds_until_eligible: float = 0.0

    @property
    def blocked(self) -> bool:
        return not self.eligible


@dataclass(frozen=True, slots=True)
class SignalShape:
    """Explicit, auditable shape of a signal (Composio A3)."""
    coin: str
    action: str
    edge_bps: float
    spread_bps: float
    status: str

    @property
    def is_actionable(self) -> bool:
        return self.status == STATUS_OK


def describe_signal(
    *,
    coin: str,
    action: str,
    edge_bps: float,
    spread_bps: float,
    age_sec: float,
    min_edge_bps: float = 10.0,
    max_spread_bps: float = 50.0,
    max_age_sec: float = 30.0,
) -> SignalShape:
    """Build the explicit signal shape with a derived status (first failing rule)."""
    if age_sec > max_age_sec:
        status = STATUS_STALE
    elif edge_bps < min_edge_bps:
        status = STATUS_LOW_EDGE
    elif spread_bps > max_spread_bps:
        status = STATUS_WIDE_SPREAD
    else:
        status = STATUS_OK
    return SignalShape(
        coin=str(coin or "").upper(),
        action=str(action or "").upper(),
        edge_bps=round(float(edge_bps), 6),
        spread_bps=round(float(spread_bps), 6),
        status=status,
    )


def check_entry_eligibility(
    *,
    coin: str,
    now_sec: float,
    recent_entry_times_sec: list[float] | None = None,
    config: EligibilityConfig | None = None,
) -> EligibilityResult:
    """Is a new paper entry on ``coin`` allowed given its recent entry times?"""
    cfg = config or EligibilityConfig()
    times = sorted(float(t) for t in (recent_entry_times_sec or []))
    if times:
        last = times[-1]
        elapsed = now_sec - last
        if elapsed < cfg.cooldown_sec:
            return EligibilityResult(
                eligible=False,
                reason="ENTRY_COOLDOWN_ACTIVE",
                seconds_until_eligible=round(cfg.cooldown_sec - elapsed, 6),
            )
    in_window = [t for t in times if now_sec - t <= cfg.window_sec]
    if len(in_window) >= cfg.max_entries_per_window:
        oldest = min(in_window)
        return EligibilityResult(
            eligible=False,
            reason="MAX_ENTRIES_PER_WINDOW",
            seconds_until_eligible=round(max(0.0, cfg.window_sec - (now_sec - oldest)), 6),
        )
    return EligibilityResult(eligible=True, reason="ELIGIBLE")


class EntryCooldownTracker:
    """Stateful per-coin entry-time tracker (in-memory, paper-only)."""

    def __init__(self, config: EligibilityConfig | None = None) -> None:
        self._cfg = config or EligibilityConfig()
        self._by_coin: dict[str, list[float]] = {}

    def register_entry(self, coin: str, now_sec: float) -> None:
        key = str(coin or "").upper()
        self._by_coin.setdefault(key, []).append(float(now_sec))
        # keep only the window to bound memory
        cutoff = now_sec - self._cfg.window_sec
        self._by_coin[key] = [t for t in self._by_coin[key] if t >= cutoff]

    def check(self, coin: str, now_sec: float) -> EligibilityResult:
        key = str(coin or "").upper()
        return check_entry_eligibility(
            coin=key,
            now_sec=now_sec,
            recent_entry_times_sec=self._by_coin.get(key, []),
            config=self._cfg,
        )


__all__ = [
    "STATUS_OK",
    "STATUS_STALE",
    "STATUS_LOW_EDGE",
    "STATUS_WIDE_SPREAD",
    "EligibilityConfig",
    "EligibilityResult",
    "SignalShape",
    "describe_signal",
    "check_entry_eligibility",
    "EntryCooldownTracker",
]
