"""AUD-113 — reconciliation CONTINUE des 5 vues : moteur / ledger / store / API / UI.

Un chiffre (equity, position nette d'un coin...) doit CONCORDER a travers ses 5 representations :
MOTEUR (etat en memoire), LEDGER (journal des fills), STORE (persistance), API (ce que la venue
rapporte, read-only) et UI (ce qui est affiche). Une divergence = un mensonge quelque part. Ce
module compare les 5 vues (a une tolerance) et liste les paires en desaccord. Une vue None =
indisponible (UNMEASURABLE, jamais 0) -> non concorde. Read-only, paper.
"""
from __future__ import annotations

from typing import Any, Mapping

VUES = ("moteur", "ledger", "store", "api", "ui")


def reconcilier_5_vues(valeurs: Mapping[str, Any], *, tolerance: float = 1e-9) -> dict:
    manquantes = [v for v in VUES if valeurs.get(v) is None]
    presentes = {v: float(valeurs[v]) for v in VUES if valeurs.get(v) is not None}
    desaccords = []
    ref = None
    if presentes:
        ref = next(iter(presentes.values()))
        for v, x in presentes.items():
            if abs(x - ref) > tolerance:
                desaccords.append({"vue": v, "valeur": x, "ref": ref, "ecart": abs(x - ref)})
    concordent = (not manquantes) and (not desaccords)
    return {"concordent": concordent, "manquantes": manquantes, "desaccords": desaccords,
            "vues_presentes": sorted(presentes), "ref": ref}


__all__ = ["reconcilier_5_vues", "VUES"]
