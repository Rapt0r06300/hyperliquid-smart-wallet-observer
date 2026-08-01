"""[COPY-VAULT #83] VAULT CONCENTRATION CEILING : un seul vault ne doit pas absorber tout le budget copy juste
parce qu'il génère PLUS de fills. On plafonne la part du budget total qu'un vault peut consommer (part_max). Un vault
bavard n'est pas un vault meilleur ; sans plafond, il monopolise le capital. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def allocation_admissible(alloc_demandee: Any, *, budget_total: Any, part_max: float = 0.4) -> dict[str, Any]:
    """Borne l'allocation d'un vault à part_max × budget_total. Entrées invalides → UNMEASURABLE + refus."""
    if not all(isinstance(x, (int, float)) for x in (alloc_demandee, budget_total)) or float(budget_total) <= 0:
        return {"alloc": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    plafond = float(part_max) * float(budget_total)
    capee = min(abs(float(alloc_demandee)), plafond)
    return {"alloc": round(capee, 8), "plafond": round(plafond, 8),
            "capee": bool(abs(float(alloc_demandee)) > plafond), "refuse": False}


__all__ = ["allocation_admissible", "UNMEASURABLE"]
