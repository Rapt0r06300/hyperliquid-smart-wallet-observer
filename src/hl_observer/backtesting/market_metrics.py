"""Métriques de marché — pures, testées. Exécution du backlog :
l2_reconstruct (IDEA-15, reconstruction du carnet depuis des updates incrémentaux),
oi_change (IDEA-44, variation d'open interest), long_short_ratio (IDEA-45). Aucun ordre.
"""
from __future__ import annotations


def l2_reconstruct(snapshot: dict, deltas) -> dict:
    """Reconstruit le carnet L2 depuis un snapshot + updates incrémentaux [(prix, taille)].
    taille <= 0 = niveau supprimé. Retourne le carnet trié par prix."""
    book = {float(p): float(s) for p, s in snapshot.items() if float(s) > 0}
    for price, size in deltas:
        price, size = float(price), float(size)
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size
    return dict(sorted(book.items()))


def oi_change(oi_series) -> float:
    """Variation relative du dernier open interest (contexte : de l'argent entre ou sort)."""
    if len(oi_series) < 2:
        return 0.0
    prev = float(oi_series[-2])
    return (float(oi_series[-1]) - prev) / prev if prev else 0.0


def long_short_ratio(longs: float, shorts: float) -> float:
    """Ratio long/short des comptes (positionnement de la foule). 0 si aucun long."""
    s = float(shorts)
    if s > 0:
        return float(longs) / s
    return float("inf") if float(longs) > 0 else 0.0
