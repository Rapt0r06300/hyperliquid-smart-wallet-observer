"""Modele de cout backtest — total round-trip + slippage depth-aware + latence (R12).

rustjesty (depth average price) + ArbiBot (latence penalise l'edge). Pur.
"""

from __future__ import annotations


def total_cost_bps(fee_bps: float, spread_bps: float, slippage_bps: float, latency_bps: float) -> float:
    return fee_bps + spread_bps + slippage_bps + latency_bps


def slippage_from_depth_bps(order_notional: float, book_levels: list[tuple[float, float]]) -> float:
    """Slippage estime en marchant le carnet L2 (prix, taille par niveau) plutot
    qu'une constante. Renvoie l'ecart moyen pondere vs le meilleur niveau, en bps.
    book_levels: [(price, size_notional), ...] du meilleur au pire."""
    if order_notional <= 0 or not book_levels:
        return 0.0
    best = book_levels[0][0]
    if best <= 0:
        return 0.0
    remaining = order_notional
    cost_price_notional = 0.0
    filled = 0.0
    for price, size in book_levels:
        if remaining <= 0:
            break
        take = min(remaining, max(0.0, size))
        cost_price_notional += price * take
        filled += take
        remaining -= take
    if filled <= 0:
        return 0.0
    avg_price = cost_price_notional / filled
    partial_penalty = 0.0
    if remaining > 0:  # carnet insuffisant : penalite pour la partie non remplie
        partial_penalty = (remaining / order_notional) * 50.0  # 50 bps par defaut si depth manque
    return abs((avg_price - best) / best) * 10000.0 + partial_penalty


def latency_penalty_bps(age_ms: int, *, edge_half_life_ms: int = 8000, max_penalty_bps: float = 40.0) -> float:
    """Penalite d'edge croissante avec l'age du signal (l'edge se decompose)."""
    if age_ms <= 0:
        return 0.0
    frac = 1.0 - 0.5 ** (age_ms / max(1, edge_half_life_ms))
    return round(max(0.0, min(max_penalty_bps, frac * max_penalty_bps)), 6)


__all__ = ["total_cost_bps", "slippage_from_depth_bps", "latency_penalty_bps"]
