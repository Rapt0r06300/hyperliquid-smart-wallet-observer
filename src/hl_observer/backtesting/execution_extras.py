"""Exécution avancée — pur, testé. Exécution du backlog :
iceberg_slices (IDEA-54), sample_latency_ms (IDEA-56), partial_fill (IDEA-57),
funding_cost (IDEA-60). Aucun ordre réel, aucune promesse.
"""
from __future__ import annotations

import random


def iceberg_slices(total_qty: float, visible_qty: float) -> list:
    """Découpe un ordre en tranches 'visibles' (iceberg) pour cacher la taille réelle."""
    total = float(total_qty)
    vis = float(visible_qty)
    if vis <= 0:
        return [total]
    n = int(total // vis)
    out = [vis] * n
    rem = total - n * vis
    if rem > 1e-12:
        out.append(rem)
    return out or [total]


def sample_latency_ms(*, mean_ms: float, jitter_ms: float, seed: int = 0, n: int = 1) -> list:
    """Échantillonne des latences réseau réalistes (gaussiennes tronquées à 0)."""
    rng = random.Random(seed)
    return [max(0.0, rng.gauss(float(mean_ms), float(jitter_ms))) for _ in range(int(n))]


def partial_fill(order_qty: float, available_qty: float) -> dict:
    """Remplissage partiel : min(ordre, dispo) rempli, le reste annulé."""
    filled = min(float(order_qty), max(0.0, float(available_qty)))
    return {"filled": filled, "unfilled": max(0.0, float(order_qty) - filled)}


def funding_cost(notional: float, *, funding_rate_per_hour_bps: float, hours_held: float) -> float:
    """Coût de financement accumulé pendant la détention (bps/h × heures × notional)."""
    return float(notional) * abs(float(funding_rate_per_hour_bps)) / 10000.0 * max(0.0, float(hours_held))
