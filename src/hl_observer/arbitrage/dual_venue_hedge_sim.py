"""Dual-venue hedge simulation, paper-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DualVenueHedgeDecision:
    accepted: bool
    reason: str
    net_edge_bps: float
    paper_only: bool = True
    real_execution: bool = False


def simulate_dual_venue_hedge(*, long_leg_price: float | None, short_leg_price: float | None, net_edge_bps: float, min_edge_bps: float = 10.0) -> DualVenueHedgeDecision:
    if long_leg_price is None or short_leg_price is None:
        return DualVenueHedgeDecision(accepted=False, reason="MISSING_LEG", net_edge_bps=float(net_edge_bps))
    if float(net_edge_bps) < float(min_edge_bps):
        return DualVenueHedgeDecision(accepted=False, reason="EDGE_TOO_LOW", net_edge_bps=float(net_edge_bps))
    return DualVenueHedgeDecision(accepted=True, reason="ACCEPT_PAPER_HEDGE", net_edge_bps=float(net_edge_bps))


__all__ = ["DualVenueHedgeDecision", "simulate_dual_venue_hedge"]
