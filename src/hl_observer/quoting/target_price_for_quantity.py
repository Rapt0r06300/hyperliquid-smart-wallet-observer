"""[EXECUTION lot2 #87] DOUBLE CALCUL TARGET PRICE FOR QUANTITY : une implémentation INDÉPENDANTE du « prix pour
absorber une quantité » (book walk), pour COMPARER au book walker principal. Deux calculs qui divergent révèlent un
bug de l'un des deux (Nautilus : get_target_px_for_quantity comme second avis). Profondeur insuffisante pour la
quantité → UNMEASURABLE (jamais extrapoler un prix au-delà du carnet). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def prix_pour_quantite(niveaux: Sequence[Any], quantite: Any) -> dict[str, Any]:
    """Parcourt les niveaux [(prix, taille)] pour absorber `quantite` ; renvoie le VWAP et le pire prix touché.
    Carnet insuffisant → UNMEASURABLE (pas d'extrapolation)."""
    if not isinstance(quantite, (int, float)) or float(quantite) <= 0:
        return {"vwap": UNMEASURABLE, "raison": "QUANTITE_INVALIDE"}
    reste = float(quantite)
    notional = 0.0
    pire = None
    for niv in niveaux:
        try:
            prix, taille = float(niv[0]), float(niv[1])
        except (TypeError, ValueError, IndexError):
            return {"vwap": UNMEASURABLE, "raison": "NIVEAU_INVALIDE"}
        pris = min(reste, taille)
        notional += pris * prix
        pire = prix
        reste -= pris
        if reste <= 1e-12:
            break
    if reste > 1e-12:
        return {"vwap": UNMEASURABLE, "raison": "CARNET_INSUFFISANT", "manque": round(reste, 12)}
    return {"vwap": round(notional / float(quantite), 10), "pire_prix": pire}


__all__ = ["prix_pour_quantite", "UNMEASURABLE"]
