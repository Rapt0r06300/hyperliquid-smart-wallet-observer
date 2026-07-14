"""Stress-testing & Monte-Carlo portefeuille — pur, testé. Exécution du backlog :
portfolio_stress (IDEA-68, scénarios extrêmes), monte_carlo_paths (IDEA-69, trajectoires),
regime_conditional_size (IDEA-70). Outils de mesure du risque ; aucun ordre, aucune promesse.
"""
from __future__ import annotations

import random


def portfolio_stress(positions: dict, shocks: dict) -> float:
    """PnL du portefeuille sous un scénario de choc. `positions` : coin -> notional signé ;
    `shocks` : coin -> rendement (ex -0.20 = crash de 20%)."""
    coins = set(positions) | set(shocks)
    return sum(float(positions.get(c, 0.0)) * float(shocks.get(c, 0.0)) for c in coins)


def monte_carlo_paths(*, mu: float, sigma: float, steps: int, n: int = 1000,
                      start: float = 1000.0, seed: int = 7) -> dict:
    """Simule n trajectoires d'équity (rendements normaux i.i.d.). Retourne médiane, p5, p95 et la
    probabilité de finir en perte — pour VOIR la distribution des issues, pas juste la moyenne."""
    rng = random.Random(seed)
    finals = []
    for _ in range(int(n)):
        eq = float(start)
        for _ in range(int(steps)):
            eq *= (1.0 + rng.gauss(float(mu), float(sigma)))
        finals.append(eq)
    finals.sort()
    L = len(finals)
    return {
        "median": finals[L // 2],
        "p5": finals[max(0, int(0.05 * L))],
        "p95": finals[min(L - 1, int(0.95 * L))],
        "prob_loss": sum(1 for x in finals if x < start) / L,
    }


def regime_conditional_size(base_size: float, *, regime_vol: float, target_vol: float) -> float:
    """Réduit la taille quand la volatilité du régime dépasse la cible (jamais au-dessus de base)."""
    rv = float(regime_vol)
    if rv <= 0:
        return float(base_size)
    return float(base_size) * min(1.0, float(target_vol) / rv)
