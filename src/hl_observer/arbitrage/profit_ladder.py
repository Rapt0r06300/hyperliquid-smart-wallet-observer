"""[CROSS-VENUE #18] PROFIT LADDER : maintenir plusieurs tranches {edge cible → taille} plutôt qu'un seul gros
ordre (architecture multi-level XEMM). Chaque tranche ne s'active que si l'edge courant atteint SON edge cible ;
les tranches les plus exigeantes ne postent qu'aux meilleurs edges. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class ProfitLadder:
    """Échelle de tranches (edge_cible_bps, taille). `ordres_actifs(edge)` = tranches dont la cible est atteinte."""

    def __init__(self, tranches: Iterable[tuple[float, float]]) -> None:
        # triées par edge cible croissant (les tranches faciles d'abord)
        self.tranches = sorted(((float(e), float(t)) for e, t in tranches), key=lambda x: x[0])

    def ordres_actifs(self, edge_courant_bps: Any) -> list[dict[str, Any]]:
        """Tranches à poster au niveau d'edge courant (cible ≤ edge). Vide si edge non mesurable."""
        if not isinstance(edge_courant_bps, (int, float)):
            return []
        return [{"edge_cible_bps": e, "taille": t} for e, t in self.tranches if edge_courant_bps >= e]

    def taille_active(self, edge_courant_bps: Any) -> float:
        return round(sum(o["taille"] for o in self.ordres_actifs(edge_courant_bps)), 12)


__all__ = ["ProfitLadder"]
