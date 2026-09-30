"""[COPY-VAULT #67] FLIP AS TWO OPERATIONS : un renversement de position (long → short ou l'inverse) est traité
comme DEUX opérations distinctes — fermer l'ancien côté, PUIS ouvrir le nouveau — avec PnL et coûts séparés.
Le traiter comme un seul ordre net brouillerait le PnL de clôture et le coût d'ouverture. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

FERMER = "FERMER"
OUVRIR = "OUVRIR"
UNMEASURABLE = "UNMEASURABLE"
_TOL = 1e-12


def decomposer(position_avant: Any, position_cible: Any) -> dict[str, Any]:
    """Si les signes diffèrent (vrai flip) → [FERMER |avant|, OUVRIR |cible|]. Même signe → simple resize (une
    seule op). Entrées invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, position_cible)):
        return {"operations": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    a, c = float(position_avant), float(position_cible)
    if a * c < -_TOL:                                    # signes opposés et non nuls → flip
        return {"flip": True, "operations": [
            {"op": FERMER, "quantite": round(abs(a), 12)},
            {"op": OUVRIR, "quantite": round(abs(c), 12)}]}
    # même côté (ou l'un est nul) : ce n'est pas un flip, juste un ajustement
    delta = c - a
    op = OUVRIR if abs(c) >= abs(a) else FERMER
    return {"flip": False, "operations": [{"op": op, "quantite": round(abs(delta), 12)}], "raison": "RESIZE"}


__all__ = ["decomposer", "FERMER", "OUVRIR", "UNMEASURABLE"]
