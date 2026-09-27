"""[ALL pépite 245] GLOBAL INTENT NETTING : étendre le netting AU-DELÀ des vaults — Copy + Cross-Venue + tout autre
module peuvent réduire leur delta AVANT passage au PaperEngine. Deux modules qui veulent +80$ et −50$ sur le même
(venue, coin) doivent produire un delta net +30$, économisant le spread/les frais sur la partie qui s'annule.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
import math
from typing idef netter(intentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate finite signed intents and preserve an input conservation receipt."""
    net: dict[tuple[str, str], float] = {}
    brut: dict[tuple[str, str], float] = {}
    included: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, it in enumerate(intentions or ()):
        if not isinstance(it, dict):
            rejected.append({"index": index, "reason": "INTENT_NOT_OBJECT"})
            continue
        amount = it.get("montant_signe")
        coin, venue = it.get("coin"), it.get("venue")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or not coin
            or not venue
        ):
            rejected.append({
                "index": index,
                "reason": "MALFORMED_OR_NON_FINITE_INTENT",
            })
            continue
        key = (str(venue).upper(), str(coin).upper())
        value = float(amount)
        net[key] = round(net.get(key, 0.0) + value, 8)
        brut[key] = round(brut.get(key, 0.0) + abs(value), 8)
        included.append({
            "index": index,
            "module": it.get("module"),
            "venue": key[0],
            "coin": key[1],
            "montant_signe": value,
        })

    result = {
        "%s/%s" % key: {
            "net": net[key],
            "brut": brut[key],
            "economie": round(brut[key] - abs(net[key]), 8),
        }
        for key in net
    }
    return {
        "net_par_cle": result,
        "n_cles": len(result),
        "included_intentions": included,
        "rejected_intentions": rejected,
        "conservation": {
            "input_count": len(included) + len(rejected),
            "included_count": len(included),
            "rejected_count": len(rejected),
            "complete": True,
        },
    }
n(resultat)}


__all__ = ["netter"]
