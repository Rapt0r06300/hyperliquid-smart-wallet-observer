"""[ARB #22] INVALIDATION-ON-MARKET-CHANGE : si le snapshot de marché utilisé pour CALCULER la décision est
remplacé (nouveau carnet reçu) AVANT la décision finale, l'opportunité doit être REVALIDÉE — jamais exécutée
sur des données déjà périmées entre le calcul et l'action. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def valider_snapshot(snapshot_id_decision: Any, snapshot_id_courant: Any) -> dict[str, Any]:
    """Décision valide seulement si le snapshot n'a pas changé entre le calcul et l'action. Sinon → REVALIDER."""
    if snapshot_id_decision is None or snapshot_id_courant is None:
        return {"valide": False, "action": "REVALIDER", "raison": "SNAPSHOT_INCONNU"}
    inchange = snapshot_id_decision == snapshot_id_courant
    return {"valide": bool(inchange), "action": ("PROCEDER" if inchange else "REVALIDER"),
            "raison": ("OK" if inchange else "SNAPSHOT_REMPLACE")}


__all__ = ["valider_snapshot"]
