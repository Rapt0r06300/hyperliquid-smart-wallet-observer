"""[ARB #39] RATE-ORACLE FAIL-CLOSED : une conversion de quote MANQUANTE ne doit JAMAIS devenir implicitement 1.0
(ni des frais implicitement à 0). Sans taux fiable, on ne compare pas deux prix dans des quotes différentes — on
refuse l'opportunité (fail-closed), on n'invente pas de parité. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def convertir(montant: Any, de: str, vers: str, *, oracle: Mapping[str, float]) -> dict[str, Any]:
    """Convertit `montant` de `de` vers `vers` via un taux exécutable de l'oracle. Même quote → pass-through.
    Taux absent → UNMEASURABLE + refus (jamais 1.0 supposé)."""
    if not isinstance(montant, (int, float)):
        return {"valeur": UNMEASURABLE, "refuse": True, "raison": "MONTANT_INVALIDE"}
    d, v = str(de).upper(), str(vers).upper()
    if d == v:
        return {"valeur": round(float(montant), 10), "taux": 1.0, "refuse": False, "raison": "MEME_QUOTE"}
    taux = oracle.get("%s->%s" % (d, v)) if isinstance(oracle, Mapping) else None
    if not isinstance(taux, (int, float)) or taux <= 0:
        return {"valeur": UNMEASURABLE, "refuse": True, "raison": "TAUX_ABSENT_FAIL_CLOSED"}
    return {"valeur": round(float(montant) * float(taux), 10), "taux": float(taux),
            "refuse": False, "raison": "OK"}


__all__ = ["convertir", "UNMEASURABLE"]
