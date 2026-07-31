"""[ARB #7] DEPEG HAIRCUT : marge de sécurité AUTOMATIQUE qui grandit quand l'écart d'un stablecoin au dollar
augmente. Un stable qui décroche (USDT à 0.985) ajoute un risque réel à toute jambe libellée dans ce stable ;
on décote l'edge en conséquence. Réutilise stablecoin_conversion.ecart_au_peg_bps. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.arbitrage.stablecoin_conversion import ecart_au_peg_bps

UNMEASURABLE = "UNMEASURABLE"


def haircut_depeg_bps(prix_executable_usd: Any, *, seuil_bps: float = 20.0, facteur: float = 1.0,
                      plafond_bps: float = 500.0) -> dict[str, Any]:
    """Haircut (bps) à retrancher de l'edge : 0 tant que |depeg| ≤ seuil, puis croît linéairement avec l'écart
    (facteur) au-delà du seuil, plafonné. Prix absent → UNMEASURABLE (prudence : on ne trade pas à l'aveugle)."""
    ecart = ecart_au_peg_bps(prix_executable_usd)
    if not isinstance(ecart, (int, float)):
        return {"haircut_bps": UNMEASURABLE, "depeg_bps": UNMEASURABLE, "raison": "PRIX_STABLE_ABSENT"}
    depeg = abs(ecart)
    haircut = min(float(plafond_bps), max(0.0, (depeg - float(seuil_bps)) * float(facteur)))
    return {"haircut_bps": round(haircut, 4), "depeg_bps": round(depeg, 4),
            "au_dela_du_seuil": bool(depeg > float(seuil_bps)), "seuil_bps": float(seuil_bps)}


def edge_apres_haircut(edge_bps: Any, prix_executable_usd: Any, *, seuil_bps: float = 20.0,
                       facteur: float = 1.0) -> Any:
    """Edge net après décote de depeg. UNMEASURABLE si l'edge ou le prix stable manque."""
    h = haircut_depeg_bps(prix_executable_usd, seuil_bps=seuil_bps, facteur=facteur)
    if not isinstance(edge_bps, (int, float)) or not isinstance(h["haircut_bps"], (int, float)):
        return UNMEASURABLE
    return round(float(edge_bps) - h["haircut_bps"], 4)


__all__ = ["haircut_depeg_bps", "edge_apres_haircut", "UNMEASURABLE"]
