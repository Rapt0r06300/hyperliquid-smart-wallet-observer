"""[ALL pépite 244] CROSS-MODULE SELF-TRADE PREVENTION : Arbitrage et Copy-Vault (et autres) ne doivent jamais
produire SIMULTANÉMENT deux intentions OPPOSÉES inutiles sur la même venue/coin (l'un veut acheter, l'autre vendre,
au même instant) — se croiser soi-même paie deux fois le spread pour un delta net nul. On détecte et on nette avant
envoi. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_TOL = 1e-12


def detecter(intentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """`intentions` = [{module, venue, coin, montant_signe}]. Détecte les (venue, coin) où deux modules ont des
    montants de SIGNES OPPOSÉS simultanés (self-trade potentiel). Renvoie ces conflits + le delta net à exécuter."""
    par_cle: dict[tuple, list[dict[str, Any]]] = {}
    for it in intentions:
        m = it.get("montant_signe")
        coin, venue = it.get("coin"), it.get("venue")
        if not isinstance(m, (int, float)) or not coin or not venue:
            continue
        par_cle.setdefault((str(venue).upper(), str(coin).upper()), []).append(it)
    conflits = []
    for cle, its in par_cle.items():
        a_achat = any(float(i["montant_signe"]) > _TOL for i in its)
        a_vente = any(float(i["montant_signe"]) < -_TOL for i in its)
        if a_achat and a_vente:
            net = sum(float(i["montant_signe"]) for i in its)
            conflits.append({"venue": cle[0], "coin": cle[1], "delta_net": round(net, 8),
                             "n_intentions": len(its)})
    return {"self_trade": bool(conflits), "conflits": conflits,
            "raison": ("OK" if not conflits else "INTENTIONS_OPPOSEES_MEME_VENUE_COIN")}


__all__ = ["detecter"]
