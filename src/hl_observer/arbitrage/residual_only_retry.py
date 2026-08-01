"""[ARB #33] RESIDUAL-ONLY RETRY : en cas d'échec PARTIEL, ne re-tenter QUE la quantité encore non couverte, jamais
la quantité initiale entière. Renvoyer l'ordre complet doublerait la partie déjà exécutée. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def quantite_a_retry(qte_cible: Any, qte_deja_couverte: Any) -> dict[str, Any]:
    """Quantité à re-tenter = cible − déjà couverte (bornée ≥ 0). Si déjà couverte inconnue → UNMEASURABLE
    (renvoyer l'ordre entier risquerait de dédoubler la partie exécutée)."""
    if not all(isinstance(x, (int, float)) for x in (qte_cible, qte_deja_couverte)):
        return {"qte_retry": UNMEASURABLE, "raison": "ETAT_COUVERTURE_INCONNU"}
    reste = float(qte_cible) - float(qte_deja_couverte)
    reste = max(0.0, reste)
    return {"qte_retry": round(reste, 12), "termine": bool(reste <= 1e-12),
            "base": "residu_uniquement"}


__all__ = ["quantite_a_retry", "UNMEASURABLE"]
