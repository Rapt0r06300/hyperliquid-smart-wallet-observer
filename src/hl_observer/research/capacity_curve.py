"""ALPHA P46 / FIX-08 / FIX-09 — BOOK WALK exécutable CORRECT + COURBE de CAPACITÉ.

Correction mathématique de l'exécution fixed-notional :
  * **BUY consomme les asks** (prix croissant), **SELL consomme les bids** (prix décroissant) ;
  * on suit le carnet niveau par niveau, on accumule la **base réellement acquise/vendue** et le **quote**
    dépensé/reçu ; **VWAP = quote / base** ;
  * **partial fill** si le carnet est insuffisant (on ne remplit jamais plus que l'affiché) ;
  * **slippage signé** : toujours ≥ 0 quand c'est adverse (BUY payé au-dessus du best ask ; SELL reçu
    sous le best bid) ;
  * tick / lot optionnels (arrondi conservateur de la base).

Capacité : slippage par notional (10/25/…/1000 $) ; `capacity_before_edge_decay` = plus grand notional dont
le slippage reste sous l'edge NET. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
NOTIONALS_DEFAUT = (10, 25, 50, 100, 250, 500, 1000)


def _cote(book: Mapping[str, Any], side: str) -> list[tuple[float, float]]:
    """Niveaux à consommer, triés dans l'ordre d'exécution. BUY→asks croissant ; SELL→bids décroissant."""
    if str(side).upper() == "BUY":
        lv = [(float(p), float(s)) for p, s in book.get("asks", []) if s and s > 0]
        lv.sort(key=lambda x: x[0])                     # meilleur ask = plus bas d'abord
    else:
        lv = [(float(p), float(s)) for p, s in book.get("bids", []) if s and s > 0]
        lv.sort(key=lambda x: -x[0])                    # meilleur bid = plus haut d'abord
    return lv


def book_walk(book: Mapping[str, Any], notional_usd: float, *, side: str,
              lot: float | None = None) -> dict[str, Any]:
    """Exécute un notional (quote/USD) contre le bon côté. VWAP, base remplie, slippage signé, partial fill."""
    niveaux = _cote(book, side)
    if not niveaux or notional_usd <= 0:
        return {"vwap": UNMEASURABLE, "base_remplie": 0.0, "quote_rempli_usd": 0.0,
                "slippage_bps": UNMEASURABLE, "partial": True, "raison": "carnet vide"}
    best = niveaux[0][0]
    reste = float(notional_usd)
    base_tot = 0.0
    quote_tot = 0.0
    for px, sz in niveaux:
        dispo_quote = px * sz
        prendre_quote = min(reste, dispo_quote)
        base = prendre_quote / px                       # base reellement acquise/vendue a ce niveau
        if lot:
            base = (int(base / lot)) * lot
            prendre_quote = base * px
        base_tot += base
        quote_tot += prendre_quote
        reste -= prendre_quote
        if reste <= 1e-9:
            break
    partial = reste > 1e-6
    if base_tot <= 0:
        return {"vwap": UNMEASURABLE, "base_remplie": 0.0, "quote_rempli_usd": 0.0,
                "slippage_bps": UNMEASURABLE, "partial": True}
    vwap = quote_tot / base_tot
    if str(side).upper() == "BUY":
        slip = (vwap - best) / best * 1e4               # >0 = paye au-dessus du best ask (adverse)
    else:
        slip = (best - vwap) / best * 1e4               # >0 = recu sous le best bid (adverse)
    return {"vwap": round(vwap, 8), "base_remplie": round(base_tot, 10),
            "quote_rempli_usd": round(quote_tot, 6), "slippage_bps": round(slip, 4), "partial": partial}


def capacity_curve(book: Mapping[str, Any], *, edge_bps: float, side: str = "BUY",
                   notionals: Sequence[int] = NOTIONALS_DEFAUT) -> dict[str, Any]:
    """Slippage par notional + capacity_before_edge_decay (plus grand notional PLEINEMENT rempli à slippage<edge)."""
    courbe: dict[int, Any] = {}
    capacity = 0.0
    for n in notionals:
        w = book_walk(book, float(n), side=side)
        s = w["slippage_bps"]
        courbe[n] = s if isinstance(s, (int, float)) else UNMEASURABLE
        # capacite = notional PLEINEMENT rempli ET slippage sous l'edge
        if isinstance(s, (int, float)) and not w["partial"] and s < edge_bps:
            capacity = float(n)
    return {"slippage_par_notional_bps": courbe, "edge_bps": edge_bps, "side": side,
            "capacity_before_edge_decay_usd": capacity}


__all__ = ["book_walk", "capacity_curve", "NOTIONALS_DEFAUT", "UNMEASURABLE"]
