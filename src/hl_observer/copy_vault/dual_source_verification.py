"""[COPY-VAULT lot2 #36] DOUBLE SOURCE WS + REST/BACKFILL : chaque vault critique doit pouvoir vérifier
PÉRIODIQUEMENT que les fills reçus en live (WS) correspondent à l'historique OFFICIEL (REST/backfill). Le live peut
manquer ou dupliquer des événements ; la source officielle fait foi. Toute divergence est remontée. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def verifier(fills_live: Iterable[Any], fills_officiels: Iterable[Any]) -> dict[str, Any]:
    """Compare les identités de fills live vs officiels. Renvoie manquants (officiels non vus en live) et
    en_trop (live absents de l'officiel). Cohérent seulement si les deux ensembles coïncident."""
    live = set(str(x) for x in fills_live)
    off = set(str(x) for x in fills_officiels)
    manquants = sorted(off - live)                       # présents à l'officiel, ratés en live
    en_trop = sorted(live - off)                         # vus en live, absents de l'officiel (doublon/fantome)
    coherent = not manquants and not en_trop
    return {"coherent": bool(coherent), "manquants": manquants, "en_trop": en_trop,
            "raison": ("OK" if coherent else "DIVERGENCE_LIVE_VS_OFFICIEL")}


__all__ = ["verifier"]
