"""Basis/funding edge model for paper arbitrage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BasisFundingEdge:
    basis_bps: float
    funding_bps: float
    hold_hours: float
    net_edge_bps: float


def estimate_basis_funding_edge(*, perp_price: float, spot_price: float, funding_bps_8h: float, hold_hours: float, cost_bps: float) -> BasisFundingEdge:
    basis = (float(perp_price) - float(spot_price)) / max(float(spot_price), 1e-9) * 10_000.0
    funding = float(funding_bps_8h) * (float(hold_hours) / 8.0)
    net = basis + funding - float(cost_bps)
    return BasisFundingEdge(basis_bps=round(basis, 8), funding_bps=round(funding, 8), hold_hours=float(hold_hours), net_edge_bps=round(net, 8))


__all__ = ["BasisFundingEdge", "estimate_basis_funding_edge"]
