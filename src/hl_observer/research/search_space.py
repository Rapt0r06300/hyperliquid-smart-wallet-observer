"""ALPHA P16 — SEARCH SPACE pré-enregistré & hashé AVANT l'OOS. Anti data-snooping.

Avant de toucher l'OOS, on ÉCRIT et on HASHE l'espace de recherche `EVENT × STATE × FILTER × HORIZON ×
EXECUTION`. La découverte explore librement cet espace ; le FREEZE choisit UNE configuration et la scelle ;
l'OOS ne fait que MESURER la config gelée. Toute config mesurée en OOS doit appartenir à l'espace enregistré
et correspondre au hash gelé — sinon c'est du snooping, on refuse.

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

DIMENSIONS = ("event", "state", "filter", "horizon", "execution")


def _canon(espace: Mapping[str, Sequence[Any]]) -> str:
    """Représentation canonique déterministe (dimensions et valeurs triées)."""
    d = {k: sorted(str(x) for x in espace.get(k, [])) for k in DIMENSIONS}
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def hash_espace(espace: Mapping[str, Sequence[Any]]) -> str:
    return hashlib.sha1(_canon(espace).encode("utf-8")).hexdigest()[:16]


def cardinalite(espace: Mapping[str, Sequence[Any]]) -> int:
    """Nombre total de configs = produit des tailles de dimension (pour la correction multiple-testing)."""
    n = 1
    for k in DIMENSIONS:
        n *= max(1, len(espace.get(k, [])))
    return n


class SearchSpace:
    """Enregistre l'espace (discovery), gèle UNE config (freeze), vérifie l'appartenance en OOS."""

    def __init__(self, espace: Mapping[str, Sequence[Any]]) -> None:
        self.espace = {k: list(espace.get(k, [])) for k in DIMENSIONS}
        self.space_hash = hash_espace(self.espace)
        self.n_configs = cardinalite(self.espace)
        self._gelee: dict[str, Any] | None = None
        self._config_hash: str | None = None

    def config_valide(self, config: Mapping[str, Any]) -> bool:
        """La config appartient-elle à l'espace enregistré ?"""
        return all(str(config.get(k)) in {str(x) for x in self.espace[k]} for k in DIMENSIONS)

    def geler(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """FREEZE : choisit une config de l'espace, la scelle avec son hash. Refuse hors espace."""
        if not self.config_valide(config):
            raise ValueError("config hors de l'espace enregistre (snooping) : %r" % dict(config))
        self._gelee = {k: config.get(k) for k in DIMENSIONS}
        self._config_hash = hashlib.sha1(
            (self.space_hash + json.dumps(self._gelee, sort_keys=True)).encode("utf-8")).hexdigest()[:16]
        return {"config": dict(self._gelee), "config_hash": self._config_hash, "space_hash": self.space_hash,
                "n_configs": self.n_configs}

    def verifier_oos(self, config_hash: str) -> bool:
        """L'OOS ne peut mesurer QUE la config gelée (même hash)."""
        return self._config_hash is not None and config_hash == self._config_hash


__all__ = ["DIMENSIONS", "hash_espace", "cardinalite", "SearchSpace"]
