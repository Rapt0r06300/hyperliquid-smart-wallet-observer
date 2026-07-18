"""MICROSTRUCTURE DU FUNDING (bloc B : idées #11/#12/#15/#17) — extraire de la structure du funding
pour classer/dimensionner. Pur, deny-by-default (entrée absente -> None/neutre). À VALIDER OOS
avant de brancher sur une décision. PAPER only, aucun ordre. (Persistance A1 existe déjà.)
"""
from __future__ import annotations

from datetime import datetime, timezone


def rang_transversal(funding_par_coin: dict) -> dict:
    """#12 : rang normalisé [0,1] du funding entre coins (0 = plus bas, 1 = plus haut). On LONG les
    bas (rang ~0), on SHORT les hauts (rang ~1). Coin sans funding numérique -> ignoré."""
    valides = {str(c): float(f) for c, f in (funding_par_coin or {}).items() if isinstance(f, (int, float))}
    if len(valides) < 2:
        return {c: 0.5 for c in valides}
    ordonnes = sorted(valides, key=lambda c: valides[c])
    return {c: round(i / (len(ordonnes) - 1), 4) for i, c in enumerate(ordonnes)}


def variance_funding(serie) -> float | None:
    """#17 : variance du funding = risque de la jambe funding. Série < 2 points -> None."""
    xs = [float(x) for x in (serie or []) if isinstance(x, (int, float))]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return round(sum((x - m) ** 2 for x in xs) / len(xs), 8)


def autocorr_lag1(serie) -> float | None:
    """#11 : auto-corrélation à lag 1 -> persistance du funding (proche +1 = très persistant).
    Série < 3 points ou variance nulle -> None (non mesurable)."""
    xs = [float(x) for x in (serie or []) if isinstance(x, (int, float))]
    if len(xs) < 3:
        return None
    m = sum(xs) / len(xs)
    denom = sum((x - m) ** 2 for x in xs)
    if denom <= 0:
        return None
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(len(xs) - 1))
    return round(num / denom, 4)


def facteur_saisonnier(ts_ms: int) -> dict:
    """#15 : contexte temporel (heure UTC, jour, weekend) pour capter une saisonnalité du funding.
    Descriptif : à confronter aux données avant tout usage décisionnel."""
    d = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
    return {"heure_utc": d.hour, "jour_semaine": d.weekday(), "weekend": d.weekday() >= 5}


__all__ = ["rang_transversal", "variance_funding", "autocorr_lag1", "facteur_saisonnier"]
