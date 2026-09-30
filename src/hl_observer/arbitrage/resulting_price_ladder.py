"""[CROSS-VENUE #2] RESULTING-PRICE-FOR-AMOUNT : le prix moyen RÉELLEMENT obtenu pour $10/$25/$50/…,
jamais seulement le best bid/ask.

Traverser le carnet niveau par niveau pour chaque montant d'un ladder et rendre le VWAP + le slippage vs
top-of-book. Réutilise arbitrage.orderbook_depth_pricer.price_from_depth (jamais d'extrapolation : si la
profondeur visible ne couvre pas le montant, `partial=True`, on n'invente pas de liquidité).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from hl_observer.arbitrage.orderbook_depth_pricer import price_from_depth

ACHAT = "ACHAT"   # on traverse les ASKS (prix croissants)
VENTE = "VENTE"   # on traverse les BIDS (prix décroissants)
MONTANTS_DEFAUT = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0)


def _niveaux_propres(levels: Iterable[Mapping[str, Any]], sens: str) -> list[dict[str, float]]:
    propres = []
    for lv in levels or ():
        try:
            p = float(lv.get("price") if lv.get("price") is not None else lv.get("px") or 0.0)
            s = float(lv.get("size") if lv.get("size") is not None else lv.get("sz") or 0.0)
        except (TypeError, ValueError):
            continue
        if p > 0 and s > 0:
            propres.append({"price": p, "size": s})
    propres.sort(key=lambda x: x["price"], reverse=(sens == VENTE))   # meilleur prix d'abord
    return propres


def resulting_price_for_amount(levels: Iterable[Mapping[str, Any]], *, sens: str = ACHAT,
                               montants: Sequence[float] = MONTANTS_DEFAUT) -> dict[str, Any]:
    """Pour chaque montant, VWAP réellement obtenu + slippage (COÛT) vs top-of-book. `sens` = ACHAT (asks) /
    VENTE (bids). Un montant qui dépasse la profondeur visible → `partial=True` (jamais extrapolé)."""
    sens = (sens or "").strip().upper()
    propres = _niveaux_propres(levels, sens)
    best = propres[0]["price"] if propres else None
    profondeur = round(sum(l["price"] * l["size"] for l in propres), 8)
    ladder = []
    for m in montants:
        r = price_from_depth(propres, target_notional_usdt=float(m))
        slip = None
        if r.average_price is not None and best and best > 0:
            brut = (r.average_price - best) if sens == ACHAT else (best - r.average_price)
            slip = round(brut / best * 1e4, 4)                       # slippage = COÛT (toujours >= 0 sur du réel)
        ladder.append({"montant_usd": float(m), "prix_moyen": r.average_price,
                       "filled_usd": r.filled_notional_usdt, "partial": r.partial, "slippage_bps": slip})
    return {"sens": sens, "best": best, "profondeur_totale_usd": profondeur, "ladder": ladder,
            "real_execution": False}


__all__ = ["ACHAT", "VENTE", "MONTANTS_DEFAUT", "resulting_price_for_amount"]
