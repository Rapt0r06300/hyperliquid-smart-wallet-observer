"""[DATA pépite 267] FIELD-LEVEL SOURCE AUTHORITY : chaque champ a UNE source autoritaire et une seule.
exchange_ts vient uniquement de la venue ; receive_ts uniquement du collector ; jamais de fallback opaque
(« si pas de exchange_ts, prends receive_ts ») qui masquerait une donnée manquante en une donnée plausible mais
fausse. Un champ dont la source ne correspond pas à son autorité, ou est absente, est refusé. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any

OK = "OK"
VIOLATION = "VIOLATION"


def valider_enregistrement(sources_par_champ: dict[str, Any], autorites: dict[str, str]) -> dict[str, Any]:
    """sources_par_champ = {champ: source_ayant_fourni}. autorites = {champ: source_autoritaire}. Pour chaque
    champ sous autorité : la source doit correspondre exactement ; absence de source = violation (pas de
    fallback). Retourne l'état global et les violations précises."""
    if not isinstance(sources_par_champ, dict) or not isinstance(autorites, dict):
        return {"etat": VIOLATION, "violations": [{"raison": "ENTREE_INVALIDE"}]}
    violations: list[dict[str, Any]] = []
    for champ, source_attendue in autorites.items():
        source_reelle = sources_par_champ.get(champ)
        if source_reelle is None:
            violations.append({"champ": champ, "raison": "SOURCE_ABSENTE", "attendue": source_attendue})
        elif source_reelle != source_attendue:
            violations.append({"champ": champ, "raison": "SOURCE_NON_AUTORITAIRE",
                               "attendue": source_attendue, "recue": source_reelle})
    etat = OK if not violations else VIOLATION
    return {"etat": etat, "conforme": not violations, "violations": violations}


__all__ = ["valider_enregistrement", "OK", "VIOLATION"]
