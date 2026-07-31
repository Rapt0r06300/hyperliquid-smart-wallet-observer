"""ALPHA P56 — FACTORY parallèle : workers READ-ONLY, UN seul writer, DÉTERMINISME quel que soit N workers.

Les workers calculent des trials en lecture seule ; un seul writer fusionne dans le registre. La fusion est
DÉTERMINISTE : dédup par trial_id, tri stable → le résultat est identique quel que soit l'ordre/nombre de
workers. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def merge_deterministe(resultats_workers: Sequence[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Fusionne les trials de plusieurs workers : dédup par trial_id (ou config_hash), tri stable."""
    par_cle: dict[str, dict[str, Any]] = {}
    for worker in resultats_workers:
        for row in worker:
            cle = str(row.get("trial_id") or row.get("config_hash") or row.get("idea"))
            if cle not in par_cle:                       # 1er writer gagne (déterministe par clé)
                par_cle[cle] = dict(row)
    return [par_cle[k] for k in sorted(par_cle)]


def resultat_invariant(merge_a: Sequence[Mapping[str, Any]], merge_b: Sequence[Mapping[str, Any]]) -> bool:
    """Deux fusions (ordres de workers différents) donnent le même résultat."""
    cle = lambda rows: [str(r.get("trial_id") or r.get("config_hash") or r.get("idea")) for r in rows]
    return cle(merge_a) == cle(merge_b)


__all__ = ["merge_deterministe", "resultat_invariant"]
