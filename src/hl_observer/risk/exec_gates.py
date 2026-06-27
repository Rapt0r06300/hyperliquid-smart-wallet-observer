"""Execution gates with V9 default thresholds (S6 — mlmodelpoly A7 + Composio).

Hard, deny-by-default vetoes evaluated before any paper entry:
  * STALE_THRESHOLD_SEC = 5      (signal age)
  * MIN_DEPTH            = 200    (USDC top-of-book/aggregated depth)
  * MAX_SPREAD_BPS       = 500    (spread veto)
  * COOLDOWN_SEC         = 30     (min gap between entries on a key)

Composes the single-purpose guards already in ``hl_observer.risk``.

SAFETY: a passed gate authorises a *paper* intent only; never a real order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.risk.liquidity_guard import liquidity_ok
from hl_observer.risk.slippage_guard import slippage_ok
from hl_observer.risk.stale_data_guard import data_fresh

STALE_THRESHOLD_SEC = 5
MIN_DEPTH_USDC = 200.0
MAX_SPREAD_BPS = 500.0
COOLDOWN_SEC = 30
MAX_SLIPPAGE_BPS = 150.0


@dataclass(frozen=True, slots=True)
class ExecGateConfig:
    stale_threshold_sec: int = STALE_THRESHOLD_SEC
    min_depth_usdc: float = MIN_DEPTH_USDC
    max_spread_bps: float = MAX_SPREAD_BPS
    cooldown_sec: int = COOLDOWN_SEC
    max_slippage_bps: float = MAX_SLIPPAGE_BPS


@dataclass(frozen=True, slots=True)
class ExecGateContext:
    signal_age_ms: int
    spread_bps: float | None
    depth_usdc: float | None
    estimated_slippage_bps: float | None = None
    seconds_since_last_entry: float | None = None


@dataclass(frozen=True, slots=True)
class ExecGateResult:
    passed: bool
    vetoes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return not self.passed


def evaluate_exec_gates(ctx: ExecGateContext, config: ExecGateConfig | None = None) -> ExecGateResult:
    cfg = config or ExecGateConfig()
    vetoes: list[str] = []

    if not data_fresh(ctx.signal_age_ms, cfg.stale_threshold_sec * 1000):
        vetoes.append("STALE_SIGNAL")

    if ctx.spread_bps is None:
        vetoes.append("SPREAD_UNKNOWN")
    elif ctx.spread_bps > cfg.max_spread_bps:
        vetoes.append("SPREAD_TOO_WIDE")

    if ctx.depth_usdc is None:
        vetoes.append("DEPTH_UNKNOWN")
    elif not liquidity_ok(ctx.depth_usdc, cfg.min_depth_usdc):
        vetoes.append("DEPTH_TOO_LOW")

    if ctx.estimated_slippage_bps is not None and not slippage_ok(
        ctx.estimated_slippage_bps, cfg.max_slippage_bps
    ):
        vetoes.append("SLIPPAGE_TOO_HIGH")

    if (
        ctx.seconds_since_last_entry is not None
        and ctx.seconds_since_last_entry < cfg.cooldown_sec
    ):
        vetoes.append("COOLDOWN_ACTIVE")

    return ExecGateResult(passed=not vetoes, vetoes=tuple(vetoes))
