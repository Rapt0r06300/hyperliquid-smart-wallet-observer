"""Detect paper triangular opportunities after costs."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.arbitrage.path_cost_model import path_cost_bps
from hl_observer.arbitrage.triangular_graph import TriangularCycle


@dataclass(frozen=True, slots=True)
class TriangularOpportunity:
    cycle: TriangularCycle
    gross_edge_bps: float
    cost_bps: float
    net_edge_bps: float
    accepted: bool
    reason: str | None


def detect_triangular_opportunities(
    cycles: list[TriangularCycle],
    *,
    min_net_edge_bps: float = 20.0,
    fee_bps_per_leg: float = 4.5,
    slippage_bps_per_leg: float = 2.0,
) -> list[TriangularOpportunity]:
    cost = path_cost_bps(legs=3, fee_bps_per_leg=fee_bps_per_leg, slippage_bps_per_leg=slippage_bps_per_leg)
    rows: list[TriangularOpportunity] = []
    for cycle in cycles:
        gross = (cycle.product_rate - 1.0) * 10_000.0
        net = gross - cost.total_cost_bps
        accepted = net >= float(min_net_edge_bps)
        rows.append(
            TriangularOpportunity(
                cycle=cycle,
                gross_edge_bps=round(gross, 8),
                cost_bps=cost.total_cost_bps,
                net_edge_bps=round(net, 8),
                accepted=accepted,
                reason=None if accepted else "TRIANGULAR_EDGE_TOO_LOW",
            )
        )
    return sorted(rows, key=lambda row: row.net_edge_bps, reverse=True)


__all__ = ["TriangularOpportunity", "detect_triangular_opportunities"]
