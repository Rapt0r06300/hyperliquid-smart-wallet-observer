"""[ALL pépite 245] GLOBAL INTENT NETTING : étendre le netting AU-DELÀ des vaults — Copy + Cross-Venue + tout autre
module peuvent réduire leur delta AVANT passage au PaperEngine. Deux modules qui veulent +80$ et −50$ sur le même
(venue, coin) doivent produire un delta net +30$, économisant le spread/les frais sur la partie qui s'annule.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def netter(intentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Agrège les intentions signées par (venue, coin), tous modules confondus, en un delta net + mesure de
    l'économie (brut − |net|). `intentions` = [{module, venue, coin, montant_signe}]."""
    net: dict[tuple, float] = {}
    brut: dict[tuple, float] = {}
    for it in intentions:
        m = it.get("montant_signe")
        coin, venue = it.get("coin"), it.get("venue")
        if not isinstance(m, (int, float)) or not coin or not venue:
            continue
        cle = (str(venue).upper(), str(coin).upper())
        net[cle] = round(net.get(cle, 0.0) + float(m), 8)
        brut[cle] = round(brut.get(cle, 0.0) + abs(float(m)), 8)
    resultat = {"%s/%s" % c: {"net": net[c], "brut": brut[c], "economie": round(brut[c] - abs(net[c]), 8)}
                for c in net}
    return {"net_par_cle": resultat, "n_cles": len(resultat)}


__all__ = ["netter"]
