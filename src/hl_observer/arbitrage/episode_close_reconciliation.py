"""[ARB pépite 237] EPISODE-CLOSE RECONCILIATION : un épisode d'arbitrage ne passe CLOSED que lorsque ordres + fills
+ positions + ledger convergent TOUS vers le même résultat. Marquer CLOSED alors qu'une des vues diverge laisse une
incohérence cachée (position résiduelle, PnL non concordant). Toute divergence → épisode NON clôturable. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-6


def peut_clore(*, position_depuis_ordres: Any, position_depuis_fills: Any, position_ledger: Any,
               residu_attendu: float = 0.0, tolerance: float = _TOL) -> dict[str, Any]:
    """CLOSED seulement si les trois vues de position (ordres, fills, ledger) coïncident (à tolérance) ET valent
    le résidu attendu (0 pour un arbitrage complet). Toute divergence → non clôturable. Donnée invalide → refus."""
    vues = {"ordres": position_depuis_ordres, "fills": position_depuis_fills, "ledger": position_ledger}
    if not all(isinstance(v, (int, float)) for v in vues.values()):
        return {"peut_clore": False, "raison": "VUE_MANQUANTE"}
    vals = [float(v) for v in vues.values()]
    convergent = (max(vals) - min(vals)) <= float(tolerance)
    au_residu = all(abs(v - float(residu_attendu)) <= float(tolerance) for v in vals)
    ok = convergent and au_residu
    div = [] if convergent else sorted(vues.keys(), key=lambda k: float(vues[k]))
    return {"peut_clore": bool(ok), "convergent": bool(convergent), "au_residu_attendu": bool(au_residu),
            "vues": {k: round(float(v), 10) for k, v in vues.items()},
            "raison": ("OK" if ok else "VUES_DIVERGENTES_OU_RESIDU")}


__all__ = ["peut_clore"]
