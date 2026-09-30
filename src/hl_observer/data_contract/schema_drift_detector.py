"""[DATA pépite 255] SCHEMA DRIFT DETECTOR : un champ disparu, un type modifié, ou une valeur d'enum nouvelle
NON déclarée = dataset mis en QUARANTAINE, jamais coercition silencieuse. On préfère refuser un dataset dont le
schéma a dérivé plutôt que « caster au mieux » et introduire un biais invisible dans les signaux. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any

OK = "OK"
QUARANTAINE = "QUARANTAINE"


def detecter(schema_reference: dict[str, str], schema_observe: dict[str, str], *,
             enums_connus: dict[str, set] | None = None,
             enums_observes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare {champ: type} de référence à l'observé. Anomalies : CHAMP_DISPARU (présent réf, absent obs),
    TYPE_MODIFIE (type différent), ENUM_NOUVEAU (valeur hors ensemble connu). Toute anomalie → QUARANTAINE."""
    if not isinstance(schema_reference, dict) or not isinstance(schema_observe, dict):
        return {"action": QUARANTAINE, "drift": True, "anomalies": [{"type": "SCHEMA_INVALIDE"}]}
    anomalies: list[dict[str, Any]] = []
    for champ, type_ref in schema_reference.items():
        if champ not in schema_observe:
            anomalies.append({"type": "CHAMP_DISPARU", "champ": champ})
        elif schema_observe[champ] != type_ref:
            anomalies.append({"type": "TYPE_MODIFIE", "champ": champ,
                              "attendu": type_ref, "observe": schema_observe[champ]})
    for champ in schema_observe:
        if champ not in schema_reference:
            anomalies.append({"type": "CHAMP_NOUVEAU", "champ": champ})
    if enums_connus and enums_observes:
        for champ, valeur in enums_observes.items():
            connus = enums_connus.get(champ)
            if connus is not None and valeur not in connus:
                anomalies.append({"type": "ENUM_NOUVEAU", "champ": champ, "valeur": valeur})
    drift = len(anomalies) > 0
    return {"action": QUARANTAINE if drift else OK, "drift": drift, "anomalies": anomalies}


__all__ = ["detecter", "OK", "QUARANTAINE"]
