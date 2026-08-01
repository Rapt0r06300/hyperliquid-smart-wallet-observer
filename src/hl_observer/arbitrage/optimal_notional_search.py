"""[ARB #16] OPTIMAL NOTIONAL SEARCH : chercher la taille qui maximise le PnL NET en DOLLARS, pas celle qui
affiche le meilleur pourcentage. Le meilleur % est à taille infinitésimale (0 slippage) mais rapporte ~0 $ ;
le meilleur $ est plus loin, jusqu'à ce que le slippage mange le gain. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def net_usd(taille: float, gross_edge_bps: float, cout_bps: Callable[[float], float]) -> float:
    """PnL net en $ pour une taille : taille × (gross − coût(taille)) / 1e4. Le coût CROÎT avec la taille."""
    return float(taille) * (float(gross_edge_bps) - float(cout_bps(taille))) / 1e4


def notional_optimal(gross_edge_bps: Any, cout_bps: Callable[[float], float],
                     tailles: Sequence[float]) -> dict[str, Any]:
    """Parmi `tailles`, renvoie celle qui MAXIMISE le net $ (pas le %). UNMEASURABLE si rien d'exploitable."""
    if not isinstance(gross_edge_bps, (int, float)) or not tailles:
        return {"taille_optimale": UNMEASURABLE, "net_usd": UNMEASURABLE}
    best_t, best_usd = None, None
    courbe = []
    for t in tailles:
        u = net_usd(t, gross_edge_bps, cout_bps)
        courbe.append({"taille": float(t), "net_usd": round(u, 8),
                       "net_bps": round(gross_edge_bps - cout_bps(t), 4)})
        if best_usd is None or u > best_usd:
            best_usd, best_t = u, float(t)
    return {"taille_optimale": best_t, "net_usd": round(best_usd, 8), "courbe": courbe,
            "note": "max $ net, pas max % (le % est trompeur a taille infinitesimale)"}


__all__ = ["net_usd", "notional_optimal", "UNMEASURABLE"]
