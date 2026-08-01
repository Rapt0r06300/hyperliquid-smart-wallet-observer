"""[RISK lot2 #90] REDUCE-ONLY CLOSE VÉRIFIÉ CONTRE LA QUANTITÉ DE POSITION : une fermeture reduce-only doit être
validée contre la QUANTITÉ DE POSITION détenue, PAS contre le cash disponible. Le bug (corrigé dans Nautilus) : une
fermeture parfaitement valide était rejetée pour « cash insuffisant » alors qu'elle ne fait que réduire une position
existante. Une réduction ≤ position détenue passe, quel que soit le cash. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-9


def peut_fermer(taille_fermeture: Any, taille_position: Any) -> dict[str, Any]:
    """Autorise la fermeture reduce-only si sa quantité ≤ |position| détenue. Le cash n'entre PAS dans ce contrôle.
    Données invalides → refus (on ne devine pas la position). Fermeture de sens opposé implicite (reduce-only)."""
    if not all(isinstance(x, (int, float)) for x in (taille_fermeture, taille_position)):
        return {"peut_fermer": False, "raison": "QUANTITE_INVALIDE"}
    q = abs(float(taille_fermeture))
    pos = abs(float(taille_position))
    ok = q <= pos + _TOL
    return {"peut_fermer": bool(ok), "qte_fermeture": round(q, 12), "qte_position": round(pos, 12),
            "verifie_contre": "POSITION_PAS_CASH",
            "raison": ("OK" if ok else "FERMETURE_SUPERIEURE_A_LA_POSITION")}


__all__ = ["peut_fermer"]
