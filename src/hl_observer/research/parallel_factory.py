"""ALPHA P56 / FIX-04 — FACTORY parallèle : workers READ-ONLY, UN seul writer, DÉTERMINISME strict.

Les workers calculent des trials en lecture seule ; un seul writer fusionne dans le registre. La fusion est
DÉTERMINISTE et vérifie le CONTENU, pas seulement les IDs :
  * dédup par empreinte de contenu complète ;
  * **conflit = même `trial_id` mais CONTENU différent → ERROR** (signale un non-déterminisme entre workers) ;
  * tri stable → résultat identique quel que soit l'ordre/nombre de workers (1/2/N).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def _cle(row: Mapping[str, Any]) -> str:
    return str(row.get("trial_id") or row.get("config_hash") or row.get("idea"))


def _empreinte(row: Mapping[str, Any]) -> str:
    return hashlib.sha1(json.dumps(dict(row), sort_keys=True, default=str).encode("utf-8")).hexdigest()


def merge_deterministe(resultats_workers: Sequence[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Fusionne les trials de plusieurs workers. Dédup par contenu ; conflit id+contenu différent = ValueError."""
    par_cle: dict[str, tuple[str, dict[str, Any]]] = {}
    for worker in resultats_workers:
        for row in worker:
            cle = _cle(row)
            emp = _empreinte(row)
            if cle in par_cle:
                if par_cle[cle][0] != emp:
                    raise ValueError(
                        "CONFLIT parallel factory : trial_id %r présent avec DEUX contenus différents "
                        "(non-déterminisme entre workers)" % cle)
                # même id + même contenu -> déjà pris, on ignore
            else:
                par_cle[cle] = (emp, dict(row))
    return [par_cle[k][1] for k in sorted(par_cle)]


def resultat_invariant(merge_a: Sequence[Mapping[str, Any]], merge_b: Sequence[Mapping[str, Any]]) -> bool:
    """Deux fusions sont invariantes si leur CONTENU complet (pas seulement les IDs) est identique, ordre inclus."""
    return [_empreinte(r) for r in merge_a] == [_empreinte(r) for r in merge_b]


__all__ = ["merge_deterministe", "resultat_invariant"]
