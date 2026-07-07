"""G5/G7/G8 — Réalisme d'exécution : probabilité de fill maker, adverse selection,
jitter de latence. Anti-optimisme du paper. Pur.
"""

from __future__ import annotations


def maker_fill_probability(*, queue_ahead_notional: float, incoming_flow_notional: float, base: float = 0.9) -> float:
    """Plus la file devant est grande vs le flux entrant, plus la prob de fill baisse."""
    q = max(0.0, float(queue_ahead_notional))
    f = max(0.0, float(incoming_flow_notional))
    if f <= 0:
        return 0.0
    ratio = f / (q + f)
    return round(max(0.0, min(1.0, base * ratio)), 6)


def adverse_selection_penalty_bps(volatility_bps: float, *, toxicity: float = 0.5) -> float:
    """Coût attendu d'être rempli surtout quand le marché va contre soi (maker toxique)."""
    return round(max(0.0, float(volatility_bps)) * max(0.0, float(toxicity)), 6)


def latency_jitter_ms(base_ms: float, *, jitter_frac: float = 0.3, sample: float = 0.5) -> float:
    """Latence variable (distribution) au lieu d'une constante. sample in [0,1]."""
    s = max(0.0, min(1.0, float(sample)))
    return round(float(base_ms) * (1.0 + float(jitter_frac) * (2.0 * s - 1.0)), 3)


__all__ = ["maker_fill_probability", "adverse_selection_penalty_bps", "latency_jitter_ms"]
