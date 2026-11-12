"""V14 #182 — Promote the exec-cost model into the NET-EDGE calculation (shadow->auth).

Net edge must survive realistic execution cost (queue/maker-rebate/L2 impact + fees + slippage
+ latency). This applies the exec cost to gross edge and, when authoritative, rejects an entry
whose NET edge falls below the floor. Stricter intersection: can only reduce trades. Pure.
"""

from __future__ import annotations

import math

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_EDGE_NEGATIVE_AFTER_EXEC_COST"
REJECT_COST_UNAVAILABLE = "REJECT_EXEC_COST_EVIDENCE_UNAVAILABLE"


def net_edge_after_exec(gross_edge_bps: float, exec_cost_bps: float) -> float:
    """Net edge = gross - execution cost (never fabricates a higher edge)."""
    return round(float(gross_edge_bps) - max(0.0, float(exec_cost_bps)), 6)


def apply_exec_cost_promotion(
    *,
    score_reason: str,
    net_edge_bps: float | None,
    min_net_edge_bps: float,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Reject an accepting score when NET edge (after exec cost) is below the floor."""
    if authoritative and score_reason == accept_marker:
        # Missing/NaN/inf economics must never become an implicit pass: comparisons
        # with NaN are false, which previously let an unmeasurable edge through.
        if net_edge_bps is None:
            return REJECT_COST_UNAVAILABLE
        try:
            net_edge = float(net_edge_bps)
            floor = float(min_net_edge_bps)
        except (TypeError, ValueError, OverflowError):
            return REJECT_COST_UNAVAILABLE
        if not math.isfinite(net_edge) or not math.isfinite(floor):
            return REJECT_COST_UNAVAILABLE
        # A zero floor means strictly positive after modeled costs; break-even
        # is not a profitable signal. For nonzero configured floors retain the
        # usual inclusive floor semantics.
        if net_edge < floor or (floor == 0.0 and net_edge <= 0.0):
            return REJECT_REASON
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_REASON", "REJECT_COST_UNAVAILABLE", "net_edge_after_exec", "apply_exec_cost_promotion"]
