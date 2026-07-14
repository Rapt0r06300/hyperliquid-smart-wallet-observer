"""Microstructure avancée — pur, testé. Exécution du backlog :
hawkes_intensity (IDEA-12, auto-excitation des ordres), maker_queue_fill_prob (IDEA-52, remplissage
maker probabiliste), adverse_selection_cost (IDEA-58, coût lié à la toxicité). Aucun ordre.
"""
from __future__ import annotations

import math


def hawkes_intensity(event_times, t: float, *, mu: float, alpha: float, beta: float) -> float:
    """Intensité conditionnelle d'un processus de Hawkes à l'instant t : chaque événement passé
    excite temporairement l'arrivée des suivants (décroissance exponentielle)."""
    return float(mu) + sum(float(alpha) * math.exp(-float(beta) * (t - ti)) for ti in event_times if ti < t)


def maker_queue_fill_prob(queue_ahead: float, *, fill_rate: float, window: float) -> float:
    """Probabilité (approx) qu'un ordre maker soit rempli : décroît avec le volume DEVANT lui dans
    la file. Modèle exponentiel P = 1 - exp(-fill_rate*window/(1+queue_ahead))."""
    denom = 1.0 + max(0.0, float(queue_ahead))
    return 1.0 - math.exp(-max(0.0, float(fill_rate)) * float(window) / denom)


def adverse_selection_cost(vpin: float, *, max_bps: float = 10.0) -> float:
    """Coût de sélection adverse (bps) croissant avec la toxicité du flux (VPIN dans [0,1])."""
    return max(0.0, min(1.0, float(vpin))) * float(max_bps)
