"""R10 — Sizing adaptatif ∝ edge net × confiance + cap d'exposition correlee.

MrFadiAi (adaptive sizing) + passivbot (exposure). Pur. Rend une taille en % de
l'equity, plafonnee par le budget correle restant. Jamais un ordre reel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SizeDecision:
    size_pct: float
    notional_usdc: float
    capped_by_correlation: bool
    reason: str


def edge_confidence_size_pct(
    edge_net_bps: float,
    confidence: float,
    *,
    base_pct: float = 0.02,
    max_pct: float = 0.10,
    edge_ref_bps: float = 50.0,
) -> float:
    """Taille croissante avec l'edge net et la confiance calibree (0..1)."""
    if edge_net_bps <= 0 or confidence <= 0:
        return 0.0
    edge_factor = min(1.0, edge_net_bps / max(1.0, edge_ref_bps))
    conf = max(0.0, min(1.0, confidence))
    return max(0.0, min(max_pct, base_pct + (max_pct - base_pct) * edge_factor * conf))


def size_with_correlation_cap(
    edge_net_bps: float,
    confidence: float,
    equity_usdc: float,
    correlated_notional_used: float,
    correlated_notional_cap: float,
    **kw,
) -> SizeDecision:
    pct = edge_confidence_size_pct(edge_net_bps, confidence, **kw)
    desired = pct * max(0.0, equity_usdc)
    room = max(0.0, correlated_notional_cap - correlated_notional_used)
    if desired <= room:
        return SizeDecision(pct, round(desired, 6), False, "OK")
    if room <= 0.0:
        return SizeDecision(0.0, 0.0, True, "CORRELATED_EXPOSURE_FULL")
    capped_pct = room / equity_usdc if equity_usdc > 0 else 0.0
    return SizeDecision(round(capped_pct, 8), round(room, 6), True, "CORRELATED_EXPOSURE_CAP")


__all__ = ["SizeDecision", "edge_confidence_size_pct", "size_with_correlation_cap"]
