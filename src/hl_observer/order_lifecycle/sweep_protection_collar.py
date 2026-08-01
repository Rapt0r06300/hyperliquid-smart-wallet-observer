"""[EXEC pépite 252] SWEEP PROTECTION COLLAR : autoriser la consommation du carnet SEULEMENT jusqu'à reference ± X
bps ; le reste devient partial/unfilled. Un ordre agressif qui mange toute la profondeur (sweep) paie des niveaux
absurdes ; le collar coupe l'exécution au-delà de la borne et laisse le reliquat non rempli plutôt que de sweeper.
On parcourt le carnet et on s'arrête à la borne. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def executer(niveaux: Sequence[Any], quantite: Any, *, prix_reference: Any, sens: Any,
             collar_bps: float = 30.0) -> dict[str, Any]:
    """Consomme le carnet pour `quantite` mais s'ARRÊTE dès qu'un niveau dépasse reference ± collar. Renvoie la
    quantité remplie (dans le collar) et le reliquat non rempli. Données invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (quantite, prix_reference)) or float(prix_reference) <= 0 \
            or float(quantite) <= 0:
        return {"remplie": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    s = str(sens).upper()
    col = float(collar_bps) / 1e4
    if s in ("ACHAT", "BUY", "LONG"):
        borne = float(prix_reference) * (1.0 + col)
        dans_collar = lambda p: p <= borne
    elif s in ("VENTE", "SELL", "SHORT"):
        borne = float(prix_reference) * (1.0 - col)
        dans_collar = lambda p: p >= borne
    else:
        return {"remplie": UNMEASURABLE, "raison": "SENS_INCONNU"}
    reste = float(quantite)
    remplie, notional = 0.0, 0.0
    for niv in niveaux:
        try:
            prix, taille = float(niv[0]), float(niv[1])
        except (TypeError, ValueError, IndexError):
            return {"remplie": UNMEASURABLE, "raison": "NIVEAU_INVALIDE"}
        if not dans_collar(prix):
            break                                        # hors collar : on ne sweepe pas au-dela
        pris = min(reste, taille)
        remplie += pris
        notional += pris * prix
        reste -= pris
        if reste <= 1e-12:
            break
    return {"remplie": round(remplie, 12), "reliquat_non_rempli": round(reste, 12),
            "vwap": (round(notional / remplie, 10) if remplie > 1e-12 else None),
            "borne_collar": round(borne, 10), "sweep_evite": bool(reste > 1e-12)}


__all__ = ["executer", "UNMEASURABLE"]
