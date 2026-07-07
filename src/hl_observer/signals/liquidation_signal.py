"""V14 #167 — LIQUIDATION cascade signal (fresh entry trigger), SHADOW.

A burst of forced liquidations is one of the freshest, most informative events on a
perp venue: forced sells (longs liquidated) flush price down; forced buys (shorts
liquidated) squeeze it up. This module QUALIFIES a recent cluster of liquidation
events for one coin into a fresh trigger and NOTES which side a copy-trader might
take. It NEVER decides the entry by itself (the scorer/risk keep the final say).

read-only / paper-only: no order, no fabrication. Returns ``None`` when there is no
fresh, significant cascade. Pure: callers pass the events + a ``now_ms`` clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log10
from typing import Iterable, Sequence


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class LiquidationEvent:
    coin: str
    liquidated_side: str   # "LONG" (forced sell) or "SHORT" (forced buy)
    notional_usdc: float
    ts_ms: int


@dataclass(frozen=True, slots=True)
class LiquidationConfig:
    window_ms: int = 60_000          # look-back window for the cascade
    max_age_ms: int = 30_000         # freshest event must be within this
    min_cascade_usdc: float = 50_000.0
    strong_cascade_usdc: float = 500_000.0
    min_count: int = 3
    mode: str = "reversion"          # "reversion" (fade the flush) or "momentum"
    read_only: bool = True
    execution: str = "forbidden"


@dataclass(frozen=True, slots=True)
class LiquidationSignal:
    coin: str
    cascade_notional_usdc: float
    count: int
    dominant_liquidated_side: str    # which side was liquidated most (by notional)
    momentum_side: str               # continuation side
    reversion_side: str              # bounce/fade side
    trigger_side: str                # the side this signal suggests (per mode)
    age_ms: int                      # age of the freshest event
    is_fresh_trigger: bool
    strength: float                  # 0..1
    mode: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = True
    execution: str = "forbidden"


def _sides_from_liquidated(dominant_liquidated: str) -> tuple[str, str]:
    """Return (momentum_side, reversion_side) given which side got liquidated.

    Longs liquidated -> forced SELLS -> price flush DOWN:
        momentum = SHORT (continuation), reversion = LONG (bounce).
    Shorts liquidated -> forced BUYS -> squeeze UP:
        momentum = LONG, reversion = SHORT.
    """
    if dominant_liquidated == "LONG":
        return "SHORT", "LONG"
    if dominant_liquidated == "SHORT":
        return "LONG", "SHORT"
    return "", ""


def build_liquidation_signal(
    events: Iterable[LiquidationEvent],
    *,
    now_ms: int,
    coin: str,
    config: LiquidationConfig | None = None,
) -> LiquidationSignal | None:
    """Qualify a fresh, significant liquidation cascade for ``coin``, else ``None``."""
    cfg = config or LiquidationConfig()
    coin_u = str(coin or "").upper()
    window: list[LiquidationEvent] = []
    for ev in events:
        if str(ev.coin or "").upper() != coin_u:
            continue
        age = int(now_ms) - int(ev.ts_ms)
        if age < 0 or age > cfg.window_ms:
            continue
        window.append(ev)
    if not window:
        return None

    notional_long = sum(max(0.0, float(e.notional_usdc)) for e in window if str(e.liquidated_side).upper() == "LONG")
    notional_short = sum(max(0.0, float(e.notional_usdc)) for e in window if str(e.liquidated_side).upper() == "SHORT")
    total = notional_long + notional_short
    count = len(window)
    freshest_age = min(int(now_ms) - int(e.ts_ms) for e in window)

    dominant = "LONG" if notional_long >= notional_short else "SHORT"
    momentum_side, reversion_side = _sides_from_liquidated(dominant)
    trigger_side = reversion_side if cfg.mode == "reversion" else momentum_side

    is_fresh = (
        total >= cfg.min_cascade_usdc
        and count >= cfg.min_count
        and freshest_age <= cfg.max_age_ms
    )

    lo = log10(max(cfg.min_cascade_usdc, 1.0))
    hi = log10(max(cfg.strong_cascade_usdc, cfg.min_cascade_usdc * 1.0001))
    size_factor = _clamp((log10(max(total, 1.0)) - lo) / max(hi - lo, 1e-9))
    fresh_factor = _clamp(1.0 - freshest_age / max(1, cfg.max_age_ms))
    count_factor = _clamp((count - cfg.min_count) / max(1.0, cfg.min_count * 3.0) + (1.0 if count >= cfg.min_count else 0.0)) if count >= cfg.min_count else _clamp(count / max(1, cfg.min_count))
    strength = _clamp(0.5 * size_factor + 0.3 * fresh_factor + 0.2 * count_factor)

    reasons: list[str] = []
    if total >= cfg.strong_cascade_usdc:
        reasons.append("LARGE_CASCADE")
    if count >= cfg.min_count:
        reasons.append("CLUSTER")
    if freshest_age <= cfg.max_age_ms:
        reasons.append("FRESH")
    reasons.append(f"DOMINANT_{dominant}_LIQUIDATED")
    reasons.append(f"MODE_{cfg.mode.upper()}")

    return LiquidationSignal(
        coin=coin_u,
        cascade_notional_usdc=round(total, 2),
        count=count,
        dominant_liquidated_side=dominant,
        momentum_side=momentum_side,
        reversion_side=reversion_side,
        trigger_side=trigger_side,
        age_ms=int(freshest_age),
        is_fresh_trigger=bool(is_fresh),
        strength=round(strength, 6),
        mode=cfg.mode,
        reasons=tuple(reasons),
    )


__all__ = [
    "LiquidationEvent",
    "LiquidationConfig",
    "LiquidationSignal",
    "build_liquidation_signal",
]
