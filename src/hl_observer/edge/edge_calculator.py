"""Net edge calculator — the quant core (S6 — V9 transversal).

edge_net = gross_edge − (taker_fee + spread + slippage + latency_decay
                         + copy_degradation + funding) + maker_rebate

This is the single place that decides whether a candidate clears the bar.
Deny-by-default: a non-positive or below-minimum net edge is rejected with
an explicit reason. Composes ``signal_decay`` (time) and
``copy_degradation`` (copy gap) helpers already in this package.

SAFETY: pure arithmetic over real cost inputs. A decision is not an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.edge.signal_decay import decay_edge


@dataclass(frozen=True, slots=True)
class EdgeNetInputs:
    gross_edge_bps: float
    taker_fee_bps: float = 0.0
    maker_rebate_bps: float = 0.0
    spread_cost_bps: float = 0.0
    slippage_bps: float = 0.0
    latency_decay_bps: float = 0.0
    copy_degradation_bps: float = 0.0
    funding_cost_bps: float = 0.0


@dataclass(frozen=True, slots=True)
class EdgeNetResult:
    gross_edge_bps: float
    total_cost_bps: float
    net_edge_bps: float
    min_edge_bps: float
    decision: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        return self.decision == "ACCEPT"


def compute_net_edge(inputs: EdgeNetInputs, *, min_edge_bps: float = 30.0) -> EdgeNetResult:
    # Costs are additive; maker rebate offsets cost (never below zero net of itself).
    total_cost = (
        max(0.0, inputs.taker_fee_bps)
        + max(0.0, inputs.spread_cost_bps)
        + max(0.0, inputs.slippage_bps)
        + max(0.0, inputs.latency_decay_bps)
        + max(0.0, inputs.copy_degradation_bps)
        + max(0.0, inputs.funding_cost_bps)
        - max(0.0, inputs.maker_rebate_bps)
    )
    net = inputs.gross_edge_bps - total_cost

    reasons: list[str] = []
    if net <= 0:
        decision = "REJECT_EDGE_NEGATIVE"
        reasons.append(f"net_edge_bps={net:.2f}<=0")
    elif net < min_edge_bps:
        decision = "REJECT_EDGE_TOO_SMALL"
        reasons.append(f"net_edge_bps={net:.2f}<min={min_edge_bps:.2f}")
    else:
        decision = "ACCEPT"
        reasons.append(f"net_edge_bps={net:.2f}>=min={min_edge_bps:.2f}")

    return EdgeNetResult(
        gross_edge_bps=inputs.gross_edge_bps,
        total_cost_bps=total_cost,
        net_edge_bps=net,
        min_edge_bps=min_edge_bps,
        decision=decision,
        reasons=tuple(reasons),
    )


def apply_time_decay(gross_edge_bps: float, *, signal_age_ms: int, half_life_ms: int) -> float:
    """Decay the gross edge by signal age before cost subtraction."""
    return decay_edge(gross_edge_bps, signal_age_ms, half_life_ms)
