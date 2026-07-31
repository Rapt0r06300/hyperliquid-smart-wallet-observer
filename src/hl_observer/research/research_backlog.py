"""ALPHA P62/P63 — gestion de recherche : bibliothèque de NÉGATIFS DURS + SCORER de backlog.

- **P62 HardNegatives** : on conserve les zones KILL prouvées et on refuse de les re-tester tant qu'il n'y a
  pas une NOUVELLE donnée ou une NOUVELLE hypothèse explicite. On ne gaspille plus de compute à ressusciter
  des morts.
- **P63 scorer** : chaque idée est notée `impact × data_readiness × independence / implementation_cost`, et
  on choisit AUTOMATIQUEMENT la prochaine TASK (la mieux notée, TODO, non bloquée).

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


class HardNegatives:
    """Zones KILL persistantes. `cle` identifie la zone (idée+config). Skip sauf nouvelle donnée/hypothèse."""

    def __init__(self, zones: Sequence[Mapping[str, Any]] | None = None) -> None:
        self._z: dict[str, dict[str, Any]] = {}
        for z in (zones or []):
            self._z[str(z.get("cle"))] = dict(z)

    def ajouter(self, cle: str, *, raison: str, dataset_hash: str | None = None,
                hypothese: str | None = None) -> None:
        self._z[str(cle)] = {"cle": str(cle), "raison": raison, "dataset_hash": dataset_hash,
                             "hypothese": hypothese}

    def doit_retester(self, cle: str, *, dataset_hash: str | None = None, hypothese: str | None = None) -> bool:
        """Re-tester SEULEMENT si zone inconnue, OU nouvelle donnée (hash différent), OU nouvelle hypothèse."""
        z = self._z.get(str(cle))
        if z is None:
            return True
        if dataset_hash is not None and dataset_hash != z.get("dataset_hash"):
            return True
        if hypothese is not None and hypothese != z.get("hypothese"):
            return True
        return False

    def to_json(self) -> str:
        return json.dumps(list(self._z.values()), ensure_ascii=False, indent=1)


def score_idee(*, impact: float, data_readiness: float, independence: float, cost: float) -> float:
    """Priorité économique = impact × readiness × independence / cost (cost>0)."""
    return round(float(impact) * float(data_readiness) * float(independence) / max(1e-9, float(cost)), 6)


def prochaine_task(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Choisit la prochaine TASK : statut TODO, non bloquée, meilleur score (ou plus petite prio_eco à défaut)."""
    candidats = [t for t in tasks if str(t.get("statut", "TODO")).upper() in ("TODO", "IN_PROGRESS")]
    if not candidats:
        return None

    def cle(t: Mapping[str, Any]) -> tuple:
        sc = t.get("score")
        if isinstance(sc, (int, float)):
            return (0, -float(sc))
        return (1, float(t.get("prio_eco", 999)))     # à défaut de score, la priorité économique pré-assignée
    return dict(min(candidats, key=cle))


__all__ = ["HardNegatives", "score_idee", "prochaine_task"]
