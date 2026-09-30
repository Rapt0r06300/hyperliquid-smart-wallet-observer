"""V14 #170 — Warmup guard: do not decide before the context is ready.

Deciding on a coin before its higher-timeframe bars and features are warmed up means
deciding on noise (mlmodelpoly uses CONTEXT_MIN_READY_BARS=200). This module reports
whether the context is ready per timeframe and offers a promotion gate that, when
authoritative, blocks entries until warmup completes.

* ``authoritative=False`` (default / shadow): no-op.
* ``warmup_ready is None`` (unknown): no-op — we only block on a *known* not-ready.

Pure / read-only: simulation verdict only, never a real order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_WARMUP_NOT_READY"

DEFAULT_REQUIRED_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h")


@dataclass(frozen=True, slots=True)
class WarmupConfig:
    min_ready_bars: int = 200
    required_tfs: tuple[str, ...] = DEFAULT_REQUIRED_TFS
    require_features: bool = True


@dataclass(frozen=True, slots=True)
class WarmupVerdict:
    ready: bool
    reason: str
    missing: tuple[str, ...] = field(default_factory=tuple)
    bars_by_tf: tuple[tuple[str, int], ...] = field(default_factory=tuple)


def warmup_status(
    *,
    bars_by_tf: Mapping[str, int] | None,
    features_ready: bool | None = True,
    config: WarmupConfig | None = None,
) -> WarmupVerdict:
    """Ready only when every required timeframe has >= min_ready_bars and features ready."""
    cfg = config or WarmupConfig()
    bars = {str(k): int(v) for k, v in (bars_by_tf or {}).items()}
    missing: list[str] = []
    for tf in cfg.required_tfs:
        have = bars.get(tf, 0)
        if have < cfg.min_ready_bars:
            missing.append(f"{tf}:{have}/{cfg.min_ready_bars}")
    if cfg.require_features and features_ready is False:
        missing.append("features:not_ready")
    ready = not missing
    reason = "READY" if ready else "WARMUP_NOT_READY"
    return WarmupVerdict(
        ready=ready,
        reason=reason,
        missing=tuple(missing),
        bars_by_tf=tuple(sorted((tf, bars.get(tf, 0)) for tf in cfg.required_tfs)),
    )


def apply_warmup_promotion(
    *,
    score_reason: str,
    warmup_ready: bool | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Stricter intersection on warmup readiness. Shadow / unknown = no-op."""
    if (
        authoritative
        and score_reason == accept_marker
        and warmup_ready is False
    ):
        return REJECT_REASON
    return score_reason


__all__ = [
    "ACCEPT_MARKER",
    "REJECT_REASON",
    "DEFAULT_REQUIRED_TFS",
    "WarmupConfig",
    "WarmupVerdict",
    "warmup_status",
    "apply_warmup_promotion",
]
