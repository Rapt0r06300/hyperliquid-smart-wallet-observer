"""V15 #203 — Correlated-exposure caps (don't stack correlated longs) + net beta."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


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
    groups = {k.upper(): v for k, v in (correlation_groups or {}).items()}
    new_group = groups.get(new_position.coin.upper(), new_position.coin.upper())
    # same-direction cluster notional (correlated stacking)
    cluster = float(new_position.notional_usd)
    for p in positions:
        g = groups.get(p.coin.upper(), p.coin.upper())
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


__all__ = ["Position", "ExposureVerdict", "correlated_exposure_check"]
