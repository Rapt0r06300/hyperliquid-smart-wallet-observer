"""[COPY-VAULT #68] POST-FILL SOURCE CONFIRMATION : après avoir reconstruit un delta à partir d'un fill, VÉRIFIER
que le snapshot de position du leader APRÈS le fill confirme bien ce delta (position_avant + delta ≈ snapshot_après).
Si le snapshot contredit le delta reconstruit, on ne fait pas confiance au delta (fill manqué, ordre partiel non
vu). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_TOL_DEFAUT = 1e-6


def confirmer(position_avant: Any, delta_reconstruit: Any, snapshot_apres: Any, *,
              tol: float = _TOL_DEFAUT) -> dict[str, Any]:
    """Confirme si avant + delta ≈ snapshot_après (à `tol` près). Toute donnée manquante → NON_CONFIRME
    (on ne suppose jamais que le delta est bon)."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, delta_reconstruit, snapshot_apres)):
        return {"confirme": False, "raison": "DONNEE_MANQUANTE"}
    attendu = float(position_avant) + float(delta_reconstruit)
    ecart = abs(attendu - float(snapshot_apres))
    ok = ecart <= float(tol)
    return {"confirme": bool(ok), "attendu": round(attendu, 12), "snapshot": round(float(snapshot_apres), 12),
            "ecart": round(ecart, 12), "raison": ("OK" if ok else "SNAPSHOT_CONTREDIT_DELTA")}


__all__ = ["confirmer"]
