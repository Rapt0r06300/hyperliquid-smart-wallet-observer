"""S2 — GESTION DE L'UNIVERS & DELISTINGS.

Détecter les coins AJOUTÉS / RETIRÉS entre deux snapshots de l'univers HL. Ne jamais tenir/ouvrir
une position sur un marché qui a disparu ou changé sous nos pieds -> fermeture propre. Deny-by-default :
un coin absent de l'univers COURANT n'est pas tradeable. PAPER only.
"""
from __future__ import annotations

from typing import Iterable


def diff_univers(precedent: Iterable[str], courant: Iterable[str]) -> dict[str, list[str]]:
    """{ajoutes, retires} entre deux snapshots (sets de coins)."""
    p, c = set(str(x).upper() for x in precedent or []), set(str(x).upper() for x in courant or [])
    return {"ajoutes": sorted(c - p), "retires": sorted(p - c)}


def coin_tradeable(coin: str, univers_courant: Iterable[str]) -> bool:
    """True seulement si le coin est dans l'univers COURANT (deny-by-default)."""
    return str(coin).upper() in set(str(x).upper() for x in univers_courant or [])


__all__ = ["diff_univers", "coin_tradeable"]
