"""B11 — FILTRE DIRECTIONNEL POST-PURGE : ne pas entrer dans le flux forcé qui vient de s'épuiser.

Après une purge de liquidations, le côté liquidé a été FORCÉ puis ÉPUISÉ : si des LONGS ont sauté,
c'est de la VENTE forcée (le prix a baissé) ; si des SHORTS ont sauté, de l'ACHAT forcé. La
direction RELÂCHÉE est l'opposé du flux épuisé : longs liquidés -> vente forcée finie -> chemin de
moindre résistance vers le HAUT (LONG relâché).

Ce module NE dit PAS « entre » : c'est un FILTRE directionnel. Il empêche d'entrer CONTRE la
direction relâchée (= chasser un mouvement forcé déjà fait / vendre dans une offre déjà purgée).
L'edge réel se valide au MARKOUT (cf. liquidation_cascade) ; ici, uniquement le filtre. PAPER only.
"""
from __future__ import annotations

from typing import Any, Iterable

NOTIONNEL_PURGE_MIN_USD = 50_000.0    # en-dessous, ce n'est pas une vraie purge -> pas de filtre


def _cote_long_et_notionnel(c: Any) -> tuple[bool | None, float]:
    """Accepte un Cluster (attributs) ou son dict (`cote_force`='VENTE' si long). -> (long?, notionnel)."""
    if hasattr(c, "long"):
        try:
            return bool(c.long), float(getattr(c, "notionnel_total_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None, 0.0
    if isinstance(c, dict):
        cf = c.get("cote_force")
        long = True if cf == "VENTE" else (False if cf == "ACHAT" else None)
        try:
            return long, float(c.get("notionnel_total_usd") or 0.0)
        except (TypeError, ValueError):
            return long, 0.0
    return None, 0.0


def _sommes(clusters: Iterable[Any]) -> tuple[float, float]:
    vente = achat = 0.0          # vente = longs liquidés (forced SELL) ; achat = shorts liquidés (forced BUY)
    for c in clusters or []:
        long, notl = _cote_long_et_notionnel(c)
        if long is True:
            vente += notl
        elif long is False:
            achat += notl
    return vente, achat


def direction_relachee(clusters: Iterable[Any], *,
                       notionnel_min: float = NOTIONNEL_PURGE_MIN_USD) -> str | None:
    """La direction RELÂCHÉE après la purge, ou None si pas de purge nette dominante.
    longs liquidés (vente forcée épuisée) -> 'LONG' ; shorts liquidés -> 'SHORT'."""
    vente, achat = _sommes(clusters)
    if max(vente, achat) < float(notionnel_min):
        return None                        # pas assez de flux forcé -> pas une purge
    if vente > achat:
        return "LONG"                      # vente forcée épuisée -> le HAUT est relâché
    if achat > vente:
        return "SHORT"
    return None                            # égalité -> pas de direction nette


def autorise(direction_trade: str, clusters: Iterable[Any], *,
             notionnel_min: float = NOTIONNEL_PURGE_MIN_USD) -> bool:
    """True si la direction du trade candidat est autorisée. Pas de purge nette -> pas de filtre
    (True). Purge -> on N'AUTORISE QUE la direction relâchée (jamais contre le flux épuisé)."""
    d = direction_relachee(clusters, notionnel_min=notionnel_min)
    if d is None:
        return True
    return str(direction_trade or "").upper() == d


__all__ = ["NOTIONNEL_PURGE_MIN_USD", "direction_relachee", "autorise"]
