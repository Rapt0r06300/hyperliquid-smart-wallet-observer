"""[CROSS-VENUE lot2 #84] BUY/SELL LEVEL STRUCTURES ASYMÉTRIQUES : la profondeur de quoting n'a AUCUNE raison d'être
identique des deux côtés. Selon l'inventaire, le skew ou le signal, on peut vouloir plus de niveaux (ou plus de
taille) côté achat que côté vente, et inversement. On valide et expose des structures de niveaux INDÉPENDANTES par
côté. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _valider(niveaux: Sequence[Any]) -> list[dict[str, Any]]:
    """Ne garde que les niveaux valides {ecart_bps>=0, taille>0}."""
    out = []
    for n in niveaux:
        e, t = (n or {}).get("ecart_bps"), (n or {}).get("taille")
        if isinstance(e, (int, float)) and isinstance(t, (int, float)) and float(e) >= 0 and float(t) > 0:
            out.append({"ecart_bps": float(e), "taille": float(t)})
    return out


def structurer(*, niveaux_buy: Sequence[Any], niveaux_sell: Sequence[Any]) -> dict[str, Any]:
    """Renvoie les structures de niveaux buy et sell, indépendantes (nombre et tailles peuvent différer)."""
    buy = _valider(niveaux_buy)
    sell = _valider(niveaux_sell)
    return {"buy": buy, "sell": sell, "n_buy": len(buy), "n_sell": len(sell),
            "asymetrique": bool(len(buy) != len(sell) or
                                sum(n["taille"] for n in buy) != sum(n["taille"] for n in sell))}


__all__ = ["structurer"]
