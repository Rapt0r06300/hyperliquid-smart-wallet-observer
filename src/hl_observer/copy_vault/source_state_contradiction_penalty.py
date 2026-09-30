"""[COPY-VAULT pépite 298] SOURCE-STATE CONTRADICTION PENALTY : si un fill dit RÉDUCTION alors que le position
report du leader indique une AUGMENTATION (ou l'inverse), les deux sources se contredisent — l'état est faux
quelque part. On ne devine pas laquelle a raison : l'épisode est QUARANTINÉ et le score de qualité du vault est
réduit. C'est un garde-fou anti-état-incohérent, dans l'esprit fail-closed. Données invalides → quarantaine
aussi. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

_REDUCTION = ("REDUCE", "CLOSE")
_AUGMENTATION = ("OPEN", "ADD")


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def evaluer(fill_action: Any, position_avant: Any, position_apres: Any, *,
            penalite: float = 0.25) -> dict[str, Any]:
    """Compare le SENS du fill (réduction/augmentation) à la variation de magnitude du position report
    (|apres| − |avant|). Réduction annoncée mais magnitude qui monte, ou augmentation annoncée mais magnitude
    qui baisse → contradiction → quarantaine + pénalité de qualité. Positions non finies → quarantaine."""
    if not (_fini(position_avant) and _fini(position_apres)):
        return {"contradiction": True, "quarantaine": True, "penalite_qualite": penalite,
                "raison": "POSITION_INVALIDE"}
    a = str(fill_action).upper()
    variation = abs(float(position_apres)) - abs(float(position_avant))
    contradiction = False
    raison = None
    if a in _REDUCTION and variation > 0:
        contradiction, raison = True, "FILL_REDUCE_MAIS_REPORT_AUGMENTE"
    elif a in _AUGMENTATION and variation < 0:
        contradiction, raison = True, "FILL_ADD_MAIS_REPORT_DIMINUE"
    elif a not in _REDUCTION and a not in _AUGMENTATION:
        return {"contradiction": False, "quarantaine": False, "penalite_qualite": 0.0,
                "raison": "ACTION_INCONNUE"}
    return {"contradiction": contradiction, "quarantaine": contradiction,
            "penalite_qualite": penalite if contradiction else 0.0, "raison": raison}


__all__ = ["evaluer"]
