"""ALPHA P46 — COURBE de CAPACITÉ : book walk + consommation, notionals 10/25/50/100/250/500/1000 USD.

Pour chaque notional, on marche le carnet (côté exécution) et on mesure le slippage moyen. La capacité =
plus grand notional dont le slippage reste sous l'edge : `capacity_before_edge_decay`. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
NOTIONALS_DEFAUT = (10, 25, 50, 100, 250, 500, 1000)


def book_walk(niveaux: Sequence[tuple[float, float]], notional_usd: float) -> dict[str, Any]:
    """Marche le carnet (liste (prix, taille_base) du meilleur au pire) pour un notional donné.

    Retourne prix moyen d'exécution + slippage bps vs meilleur prix, ou UNMEASURABLE si liquidité insuffisante.
    """
    if not niveaux or notional_usd <= 0:
        return {"slippage_bps": UNMEASURABLE, "rempli_usd": 0.0}
    best = niveaux[0][0]
    reste = float(notional_usd)
    cout = 0.0
    rempli = 0.0
    for px, sz in niveaux:
        cap_usd = px * sz
        prendre = min(reste, cap_usd)
        cout += prendre                                   # en USD (approx : prix ~ px sur la tranche)
        rempli += prendre
        reste -= prendre
        if reste <= 1e-9:
            break
    if reste > 1e-6:
        return {"slippage_bps": UNMEASURABLE, "rempli_usd": round(rempli, 4), "raison": "liquidite insuffisante"}
    # prix moyen pondéré par tranche
    reste = float(notional_usd)
    somme_px_pond = 0.0
    for px, sz in niveaux:
        cap_usd = px * sz
        prendre = min(reste, cap_usd)
        somme_px_pond += px * prendre
        reste -= prendre
        if reste <= 1e-9:
            break
    px_moyen = somme_px_pond / notional_usd
    slip = (px_moyen / best - 1.0) * 1e4
    return {"prix_moyen": round(px_moyen, 8), "slippage_bps": round(slip, 4), "rempli_usd": round(notional_usd, 4)}


def capacity_curve(niveaux: Sequence[tuple[float, float]], *, edge_bps: float,
                   notionals: Sequence[int] = NOTIONALS_DEFAUT) -> dict[str, Any]:
    """Slippage par notional + capacity_before_edge_decay (plus grand notional où slippage < edge)."""
    courbe = {}
    capacity = 0.0
    for n in notionals:
        w = book_walk(niveaux, float(n))
        courbe[n] = w["slippage_bps"]
        if isinstance(w["slippage_bps"], (int, float)) and w["slippage_bps"] < edge_bps:
            capacity = float(n)
    return {"slippage_par_notional_bps": courbe, "edge_bps": edge_bps,
            "capacity_before_edge_decay_usd": capacity}


__all__ = ["book_walk", "capacity_curve", "NOTIONALS_DEFAUT", "UNMEASURABLE"]
