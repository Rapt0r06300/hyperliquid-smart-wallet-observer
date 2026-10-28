"""[COPY-VAULT lot2 #64] LEADER OPERATIONAL-QUALITY SCORE.

Les erreurs, reconnects, états incohérents, cadence extrême et données absentes deviennent une pénalité
distincte du PnL. Un leader très rentable mais opérationnellement chaotique (qu'on réplique mal) n'est
pas un bon leader à copier. Score [0,1]. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


def score(*, erreurs: Any = 0, reconnects: Any = 0, etats_incoherents: Any = 0,
          cadence_extreme: bool = False, donnees_absentes: Any = 0) -> dict[str, Any]:
    """Part de 1.0 et retranche pour chaque catégorie de défaut opérationnel. Valeurs invalides comptent comme
    défaut (score plus bas, jamais gonflé). Indépendant du PnL."""
    def _n(x: Any) -> int:
        if isinstance(x, bool):
            return 1
        if isinstance(x, int):
            return x if x >= 0 else 1
        if isinstance(x, float) and math.isfinite(x) and x >= 0 and x.is_integer():
            return int(x)
        return 1

    s = 1.0
    penalites = {}
    for nom, val, poids in (("erreurs", _n(erreurs), 0.1), ("reconnects", _n(reconnects), 0.08),
                            ("etats_incoherents", _n(etats_incoherents), 0.15),
                            ("donnees_absentes", _n(donnees_absentes), 0.1)):
        if val > 0:
            p = min(0.5, poids * val)
            s -= p
            penalites[nom] = round(p, 4)
    if bool(cadence_extreme):
        s -= 0.15
        penalites["cadence_extreme"] = 0.15
    s = max(0.0, min(1.0, s))
    return {"operational_quality": round(s, 4), "penalites": penalites, "distinct_du_pnl": True}


__all__ = ["score"]
