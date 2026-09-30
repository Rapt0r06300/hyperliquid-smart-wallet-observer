"""L3 — ANTI-GAMING : randomiser TAILLE et TIMING pour ne pas être prévisible.

Des ordres réguliers (même taille, même cadence) se font détecter et exploiter par les MM adverses.
On ajoute un jitter BORNÉ et déterministe (seedable pour les tests) sur la taille et le délai.
Ne change jamais le SIGNE ni ne dépasse les bornes. PAPER only.
"""
from __future__ import annotations

import random


def taille_randomisee(base: float, *, jitter_frac: float = 0.15, rng: random.Random | None = None) -> float:
    """base × (1 ± jitter_frac). jitter borné à [0, 1[. Toujours > 0 si base > 0."""
    r = rng or random
    j = min(0.99, max(0.0, float(jitter_frac)))
    facteur = 1.0 + r.uniform(-j, j)
    return max(0.0, float(base) * facteur)


def delai_randomise_ms(base_ms: float, *, jitter_ms: float = 500.0, rng: random.Random | None = None) -> float:
    """base_ms + jitter dans [0, jitter_ms] (jamais négatif : on n'accélère pas artificiellement)."""
    r = rng or random
    return max(0.0, float(base_ms) + r.uniform(0.0, max(0.0, float(jitter_ms))))


__all__ = ["taille_randomisee", "delai_randomise_ms"]
