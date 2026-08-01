"""[DATA pépite 266] ADAPTER CONFORMANCE SUITE : tous les connecteurs (adaptateurs de venue) doivent satisfaire
EXACTEMENT les mêmes invariants sur price / qty / side / ts / sequence. Un adaptateur qui laisse passer un side
inconnu ou un prix négatif casse le reste du pipeline en aval ; cette suite vérifie un événement canonique
contre le contrat commun, identique pour toute venue. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

CONFORME = "CONFORME"
NON_CONFORME = "NON_CONFORME"
_SIDES = {"BUY", "SELL", "ACHAT", "VENTE", "B", "S"}


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def verifier_conformite(evenement: dict[str, Any], *, exige_sequence: bool = False) -> dict[str, Any]:
    """Invariants communs : price fini > 0 ; qty finie > 0 ; side dans l'ensemble autorisé ; ts fini > 0 ;
    sequence entière si exigée. Toute violation → NON_CONFORME avec la liste des manquements (fail-closed)."""
    if not isinstance(evenement, dict):
        return {"etat": NON_CONFORME, "violations": ["EVENEMENT_INVALIDE"]}
    v: list[str] = []
    if not _fini(evenement.get("price")) or evenement.get("price", 0) <= 0:
        v.append("PRICE")
    if not _fini(evenement.get("qty")) or evenement.get("qty", 0) <= 0:
        v.append("QTY")
    if str(evenement.get("side", "")).upper() not in _SIDES:
        v.append("SIDE")
    if not _fini(evenement.get("ts")) or evenement.get("ts", 0) <= 0:
        v.append("TS")
    if exige_sequence and not isinstance(evenement.get("sequence"), int):
        v.append("SEQUENCE")
    conforme = len(v) == 0
    return {"etat": CONFORME if conforme else NON_CONFORME, "conforme": conforme, "violations": v}


__all__ = ["verifier_conformite", "CONFORME", "NON_CONFORME"]
