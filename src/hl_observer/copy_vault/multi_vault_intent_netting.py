"""[COPY-VAULT #80] MULTI-VAULT INTENT NETTING : si deux vaults demandent simultanément +$80 et −$50 sur le MÊME
coin, produire un delta NET +$30 au lieu d'exécuter deux trades coûteux qui se compensent en partie. Le netting
économise le spread et les frais sur la partie qui s'annule. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
import math
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


def netting_attribution_receipt(intents: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate observed intents before measuring netting and source attribution."""
    rows = list(intents)
    if not rows:
        return {"status": "UNMEASURABLE", "reason": "NO_INTENTS"}
    for row in rows:
        if not isinstance(row, dict):
            return {"status": "UNMEASURABLE", "reason": "INTENT_INVALID"}
        coin = row.get("coin")
        amount = row.get("montant_signe")
        vault = row.get("vault_id", row.get("vault"))
        if (
            not isinstance(coin, str)
            or not coin.strip()
            or isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or not isinstance(vault, str)
            or not vault.strip()
        ):
            return {"status": "UNMEASURABLE", "reason": "INTENT_ATTRIBUTION_INVALID"}
    result = netter(rows)
    sources: dict[str, list[str]] = {}
    for row in rows:
        coin = str(row["coin"]).upper()
        vault = str(row.get("vault_id", row.get("vault")))
        sources.setdefault(coin, []).append(vault)
    return {
        "status": "PROVEN",
        **result,
        "attribution_by_coin": {coin: sorted(values) for coin, values in sorted(sources.items())},
        "real_execution": False,
    }


__all__ = ["netter", "netting_attribution_receipt"]
