"""[COPY-VAULT #80] MULTI-VAULT INTENT NETTING : si deux vaults demandent simultanément +$80 et −$50 sur le MÊME
coin, produire un delta NET +$30 au lieu d'exécuter deux trades coûteux qui se compensent en partie. Le netting
économise le spread et les frais sur la partie qui s'annule. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def netter(intents: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Agrège les intents signés par coin en un delta net. `intents` = [{coin, montant_signe(_usd)}].
    Retourne le delta net par coin + le brut (somme des |montants|) pour mesurer l'économie de netting."""
    net: dict[str, float] = {}
    brut: dict[str, float] = {}
    for it in intents:
        coin = str(it.get("coin", "")).upper()
        m = it.get("montant_signe")
        if not coin or not isinstance(m, (int, float)):
            continue
        net[coin] = round(net.get(coin, 0.0) + float(m), 8)
        brut[coin] = round(brut.get(coin, 0.0) + abs(float(m)), 8)
    economie = {c: round(brut[c] - abs(net[c]), 8) for c in net}   # partie qui s'annule (spread/frais évités)
    return {"net_par_coin": net, "brut_par_coin": brut, "economie_par_coin": economie}


__all__ = ["netter"]
