"""V14 #178 — Top1/top3 depth thresholds + spread tiers before EACH entry.

Composes the existing depth_guard with explicit top-of-book (top1) and top-3 depth floors
and spread tiers (OK / DEGRADED / BAD) — mlmodelpoly's MIN_TOP1_USD=20, MIN_TOP3_USD=60,
DEGRADED=400 bps, BAD=800 bps. Pure; promotion is opt-in and can only reduce trades.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.signals.depth_guard import depth_guard

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_DEPTH_OR_SPREAD"


@dataclass(frozen=True, slots=True)
class DepthSpreadConfig:
    min_top1_usd: float = 20.0
    min_top3_usd: float = 60.0
    min_book_depth_usd: float = 200.0
    max_consume_fraction: float = 0.25
    degraded_spread_bps: float = 400.0
    bad_spread_bps: float = 800.0


def spread_tier(spread_bps: float, *, degraded_bps: float = 400.0, bad_bps: float = 800.0) -> str:
    s = float(spread_bps)
    if s >= bad_bps:
        return "BAD"
    if s >= degraded_bps:
        return "DEGRADED"
    return "OK"


@dataclass(frozen=True, slots=True)
class DepthSpreadVerdict:
    ok: bool
    reason: str | None
    spread_tier: str


def depth_spread_gate(
    *,
    top1_usd: float,
    top3_usd: float,
    bid_depth_usd: float,
    ask_depth_usd: float,
    side: str,
    needed_usd: float,
    config: DepthSpreadConfig | None = None,
    spread_bps: float = 0.0,
) -> DepthSpreadVerdict:
    """Block thin top-of-book / too-wide spread before an entry."""
    cfg = config or DepthSpreadConfig()
    tier = spread_tier(spread_bps, degraded_bps=cfg.degraded_spread_bps, bad_bps=cfg.bad_spread_bps)
    if float(top1_usd) < cfg.min_top1_usd:
        return DepthSpreadVerdict(False, "TOP1_TOO_THIN", tier)
    if float(top3_usd) < cfg.min_top3_usd:
        return DepthSpreadVerdict(False, "TOP3_TOO_THIN", tier)
    if tier == "BAD":
        return DepthSpreadVerdict(False, "SPREAD_BAD", tier)
    ok, why = depth_guard(
        bid_depth_usd=bid_depth_usd, ask_depth_usd=ask_depth_usd, side=side,
        needed_usd=needed_usd, min_depth_usd=cfg.min_book_depth_usd,
        max_consume_fraction=cfg.max_consume_fraction,
    )
    if not ok:
        return DepthSpreadVerdict(False, why, tier)
    return DepthSpreadVerdict(True, None, tier)


def apply_depth_spread_promotion(
    *,
    score_reason: str,
    gate_ok: bool | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Veto entries that fail the depth/spread gate. None (unknown) never blocks. Shadow = no-op."""
    if authoritative and score_reason == accept_marker and gate_ok is False:
        return REJECT_REASON
    return score_reason


__all__ = [
    "ACCEPT_MARKER",
    "REJECT_REASON",
    "DepthSpreadConfig",
    "spread_tier",
    "DepthSpreadVerdict",
    "depth_spread_gate",
    "apply_depth_spread_promotion",
]
