"""V15 #203 — Correlated-exposure caps (don't stack correlated longs) + net beta."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping, Sequence

from hl_observer.instrument_identity import preserve_native_instrument_symbol

@dataclass(frozen=True, slots=True)
class Position:
    coin: str
    side: str
    notional_usd: float
    beta: float = 1.0


@dataclass(frozen=True, slots=True)
class ExposureVerdict:
    ok: bool
    reason: str | None
    cluster_notional_usd: float
    net_beta: float


def _signed(notional: float, side: str) -> float:
    return float(notional) if str(side).upper() in {"LONG", "BUY"} else -float(notional)


def correlated_exposure_check(
    positions: Sequence[Position],
    new_position: Position,
    *,
    correlation_groups: Mapping[str, str] | None = None,   # coin -> group id
    max_cluster_notional_usd: float = 300.0,
    max_net_beta_usd: float = 600.0,
) -> ExposureVerdict:
    """Block a new position that over-concentrates a correlated cluster or net beta."""
    groups = {preserve_native_instrument_symbol(k): v for k, v in (correlation_groups or {}).items()}
    new_coin = preserve_native_instrument_symbol(new_position.coin)
    new_group = groups.get(new_coin, new_coin)
    # same-direction cluster notional (correlated stacking)
    cluster = float(new_position.notional_usd)
    for p in positions:
        coin = preserve_native_instrument_symbol(p.coin)
        g = groups.get(coin, coin)
        if g == new_group and str(p.side).upper() == str(new_position.side).upper():
            cluster += float(p.notional_usd)
    # net beta across the book (signed by side, weighted by beta)
    net_beta = _signed(new_position.notional_usd, new_position.side) * float(new_position.beta)
    for p in positions:
        net_beta += _signed(p.notional_usd, p.side) * float(p.beta)
    if cluster > max_cluster_notional_usd:
        return ExposureVerdict(False, "CORRELATED_CLUSTER_CAP", round(cluster, 2), round(net_beta, 2))
    if abs(net_beta) > max_net_beta_usd:
        return ExposureVerdict(False, "NET_BETA_CAP", round(cluster, 2), round(net_beta, 2))
    return ExposureVerdict(True, None, round(cluster, 2), round(net_beta, 2))


def correlated_exposure_receipt(
    positions: Sequence[Position],
    new_position: Position,
    *,
    correlation_groups: Mapping[str, str] | None = None,
    max_cluster_notional_usd: float = 300.0,
    max_net_beta_usd: float = 600.0,
) -> dict[str, object]:
    """Return a fail-closed, paper-only receipt for the concentration check."""
    if not isinstance(positions, Sequence) or not isinstance(new_position, Position):
        return {"status": "UNMEASURABLE", "reason": "POSITIONS_INVALID"}
    all_positions = [*positions, new_position]
    if any(
        not isinstance(position, Position)
        or not isinstance(position.coin, str)
        or not position.coin.strip()
        or not isinstance(position.side, str)
        or not position.side.strip()
        or isinstance(position.notional_usd, bool)
        or not isinstance(position.notional_usd, (int, float))
        or not math.isfinite(float(position.notional_usd))
        or isinstance(position.beta, bool)
        or not isinstance(position.beta, (int, float))
        or not math.isfinite(float(position.beta))
        for position in all_positions
    ):
        return {"status": "UNMEASURABLE", "reason": "POSITION_OBSERVATION_INVALID"}
    if (
        isinstance(max_cluster_notional_usd, bool)
        or not isinstance(max_cluster_notional_usd, (int, float))
        or not math.isfinite(float(max_cluster_notional_usd))
        or float(max_cluster_notional_usd) < 0
        or isinstance(max_net_beta_usd, bool)
        or not isinstance(max_net_beta_usd, (int, float))
        or not math.isfinite(float(max_net_beta_usd))
        or float(max_net_beta_usd) < 0
    ):
        return {"status": "UNMEASURABLE", "reason": "CAP_INVALID"}
    verdict = correlated_exposure_check(
        positions,
        new_position,
        correlation_groups=correlation_groups,
        max_cluster_notional_usd=float(max_cluster_notional_usd),
        max_net_beta_usd=float(max_net_beta_usd),
    )
    return {
        "status": "PROVEN",
        "allowed": verdict.ok,
        "reason": verdict.reason,
        "cluster_notional_usd": verdict.cluster_notional_usd,
        "net_beta": verdict.net_beta,
        "real_execution": False,
    }


__all__ = ["Position", "ExposureVerdict", "correlated_exposure_check", "correlated_exposure_receipt"]
