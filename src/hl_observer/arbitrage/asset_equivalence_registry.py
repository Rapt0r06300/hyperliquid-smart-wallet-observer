"""[ARB #8] ASSET-EQUIVALENCE REGISTRY : mapping EXPLICITE des actifs équivalents (BTC/WBTC/XBT, ETH/WETH…),
jamais un rapprochement par nom. « BTC » sur une venue et « WBTC » sur une autre ne sont équivalents que si on
l'a DÉCLARÉ ; deux symboles au nom proche mais non déclarés ne sont PAS rapprochés. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: groupes d'équivalence par actif canonique. Explicite — on n'infère jamais par ressemblance de nom.
EQUIVALENCES_DEFAUT: dict[str, set[str]] = {
    "BTC": {"BTC", "WBTC", "XBT", "BTCB", "BTC.B"},
    "ETH": {"ETH", "WETH", "BETH", "STETH", "WSTETH"},
    "SOL": {"SOL", "WSOL"},
    "USDC": {"USDC", "USDC.E"},
    "USDT": {"USDT", "USDT.E"},
}


class RegistreEquivalence:
    """Canonicalise un symbole vers son actif canonique, UNIQUEMENT via des groupes déclarés."""

    def __init__(self, groupes: Mapping[str, Iterable[str]] | None = None) -> None:
        self._canon: dict[str, str] = {}
        for canon, alias in (groupes or EQUIVALENCES_DEFAUT).items():
            for a in set(alias) | {canon}:
                self._canon[str(a).upper()] = str(canon).upper()

    def canonique(self, symbole: Any) -> str | None:
        """Actif canonique du symbole, ou None s'il n'est pas déclaré (jamais deviné)."""
        if symbole is None:
            return None
        return self._canon.get(str(symbole).upper())

    def equivalents(self, a: Any, b: Any) -> bool:
        """True seulement si a et b canonicalisent vers le MÊME actif déclaré. Un non-déclaré n'est équivalent à rien."""
        ca, cb = self.canonique(a), self.canonique(b)
        return ca is not None and ca == cb

    def declarer(self, canon: str, alias: Iterable[str]) -> None:
        for a in set(alias) | {canon}:
            self._canon[str(a).upper()] = str(canon).upper()


__all__ = ["RegistreEquivalence", "EQUIVALENCES_DEFAUT"]
