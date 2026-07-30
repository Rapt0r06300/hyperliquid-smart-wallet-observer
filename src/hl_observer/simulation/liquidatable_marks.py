"""P1A — construire les marks LIQUIDABLES exécutables (LONG@bid, SHORT@ask) pour l'equity autoritaire.

Tout le calcul d'equity liquidable EXISTE déjà (`LedgerPosition.liquidatable_unrealized`,
`PaperLedger.mark_to_market(liquidatable_marks=...)`, `CapitalAccountingTracker`, `equity_canonique`).
Le SEUL trou mesuré : **aucun appelant ne fournit `liquidatable_marks`** → `last_liquidatable_price`
reste `None` → l'equity autoritaire tombe en `UNMEASURABLE_NO_EXECUTABLE_EXIT` en permanence.

Ce module produit exactement ce dict, à partir du carnet CAUSAL : une position **LONG** se dénoue en
**VENDANT au meilleur BID** exécutable ; une position **SHORT** en **ACHETANT au meilleur ASK**.
Cross-venue : chaque jambe est marquée de son côté de sortie.

Règle dure : sans bid/ask exécutable pour une position, **pas** de mark liquidable pour elle (elle
reste `UNMEASURABLE`), JAMAIS un repli silencieux sur le mid. Le mid reste diagnostic. La clé de
sortie reflète `PaperLedger._position_mark` (`position_id`, sinon `COIN:SIDE`). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

SCHEMA_VERSION = "hypersmart.liquidatable_marks.v1"

#: Côté de SORTIE d'une position : une LONG vend (bid), une SHORT achète (ask).
_LONG = ("LONG", "BUY", "B", "BID", "1", "+1")
_SHORT = ("SHORT", "SELL", "S", "ASK", "-1")


def _pos(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _attr(p: Any, name: str) -> Any:
    if isinstance(p, Mapping):
        return p.get(name)
    return getattr(p, name, None)


def _bbo(entry: Any) -> tuple[float | None, float | None]:
    """Extrait (bid, ask) d'un `{"bid":..,"ask":..}` / `{"best_bid":..,"best_ask":..}` ou `(bid, ask)`."""
    if isinstance(entry, Mapping):
        return _pos(entry.get("bid", entry.get("best_bid"))), _pos(entry.get("ask", entry.get("best_ask")))
    try:
        return _pos(entry[0]), _pos(entry[1])
    except (TypeError, IndexError, KeyError):
        return None, None


def mark_liquidatable(side: object, *, best_bid: object = None, best_ask: object = None) -> float | None:
    """Prix de dénouement exécutable d'une position. LONG→bid, SHORT→ask. `None` si le côté manque."""
    s = str(side or "").strip().upper()
    if s in _LONG:
        return _pos(best_bid)      # sortir d'une LONG = vendre dans le bid
    if s in _SHORT:
        return _pos(best_ask)      # sortir d'une SHORT = acheter à l'ask
    return None


def _cle_sortie(coin: str, side: str, position_id: object) -> str:
    if position_id not in (None, ""):
        return str(position_id)
    return f"{str(coin).upper()}:{str(side).upper()}"


def marks_depuis_bbo(positions: Iterable[Any], bbo: Mapping[str, Any]) -> dict[str, float]:
    """Construit le dict `liquidatable_marks` attendu par `PaperLedger.mark_to_market`.

    `positions` : itérable de `LedgerPosition` ou de dicts `{position_id, coin, side}`.
    `bbo` : mapping `coin -> {"bid":.., "ask":..}` (ou `(bid, ask)`).
    Clé de sortie = `position_id` si présent, sinon `COIN:SIDE`. Une position sans bid/ask exécutable
    côté sortie est **omise** (elle restera UNMEASURABLE côté equity autoritaire — c'est voulu)."""
    out: dict[str, float] = {}
    for p in positions:
        coin, side = _attr(p, "coin"), _attr(p, "side")
        if not coin or not side:
            continue
        entry = bbo.get(str(coin).upper()) if isinstance(bbo, Mapping) else None
        if entry is None and isinstance(bbo, Mapping):
            entry = bbo.get(str(coin))
        bid, ask = _bbo(entry or {})
        mk = mark_liquidatable(side, best_bid=bid, best_ask=ask)
        if mk is None:
            continue
        out[_cle_sortie(str(coin), str(side), _attr(p, "position_id"))] = mk
    return out


def marks_depuis_execution_truths(positions: Iterable[Any], truths: Mapping[str, Any]) -> dict[str, float]:
    """Variante câblage : `truths` = mapping `coin -> objet portant best_bid/best_ask` (ex. `ExecutionTruth`)."""
    bbo: dict[str, Any] = {}
    for coin, t in (truths or {}).items():
        bbo[str(coin).upper()] = {
            "bid": _attr(t, "best_bid"),
            "ask": _attr(t, "best_ask"),
        }
    return marks_depuis_bbo(positions, bbo)


def couverture(positions: Iterable[Any], marks: Mapping[str, float]) -> dict[str, Any]:
    """Part des positions réellement marquées liquidables (le reste = UNMEASURABLE, nommé et compté)."""
    pos = list(positions)
    total = len(pos)
    mesurees = 0
    manquantes: list[str] = []
    for p in pos:
        coin, side = _attr(p, "coin"), _attr(p, "side")
        cle = _cle_sortie(str(coin), str(side), _attr(p, "position_id"))
        alt = f"{str(coin).upper()}:{str(side).upper()}"
        if cle in marks or alt in marks or str(coin).upper() in marks:
            mesurees += 1
        else:
            manquantes.append(cle)
    return {
        "schema_version": SCHEMA_VERSION,
        "n_positions": total,
        "n_liquidatable_mesurees": mesurees,
        "n_unmeasurable": total - mesurees,
        "positions_unmeasurable": manquantes,
        "couverture": round(mesurees / total, 6) if total else None,
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "mark_liquidatable", "marks_depuis_bbo",
    "marks_depuis_execution_truths", "couverture",
]
