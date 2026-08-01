"""[DATA pépite 257] FIXED-POINT SERIALIZATION CONTRACT : si le moteur travaille en Decimal / fixed-point, le
format disque ne doit JAMAIS réintroduire des floats. Un champ prix/quantité sérialisé en float binaire peut
perdre des chiffres (0.1 non représentable) ; le contrat exige str ou int scalé. On détecte toute violation
plutôt que de « recaster » silencieusement à la relecture. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

CONFORME = "CONFORME"
VIOLATION = "VIOLATION"


def _est_float(v: Any) -> bool:
    # bool est un int en Python ; on ne le considère pas comme float.
    return isinstance(v, float)


def verifier_contrat(enregistrement: dict[str, Any], champs_fixed_point: list[str]) -> dict[str, Any]:
    """Chaque champ fixed-point sérialisé doit être str ou int (jamais float). Champ absent → violation aussi
    (on ne tolère pas un fixed-point manquant en douce). Retourne l'état et la liste précise des violations."""
    if not isinstance(enregistrement, dict):
        return {"etat": VIOLATION, "violations": [{"raison": "ENREGISTREMENT_INVALIDE"}]}
    violations: list[dict[str, Any]] = []
    for champ in champs_fixed_point:
        if champ not in enregistrement:
            violations.append({"champ": champ, "raison": "CHAMP_ABSENT"})
        elif _est_float(enregistrement[champ]):
            violations.append({"champ": champ, "raison": "FLOAT_INTERDIT", "valeur": enregistrement[champ]})
    conforme = len(violations) == 0
    return {"etat": CONFORME if conforme else VIOLATION, "conforme": conforme, "violations": violations}


__all__ = ["verifier_contrat", "CONFORME", "VIOLATION"]
