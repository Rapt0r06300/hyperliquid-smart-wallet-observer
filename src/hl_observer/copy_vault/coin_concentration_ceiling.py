"""[COPY-VAULT #84] COIN CONCENTRATION CEILING : plusieurs vaults qui copient le MÊME coin restent une SEULE
concentration économique. On agrège l'exposition de tous les vaults sur un coin et on la plafonne à part_max de
notre equity — sinon trois vaults « diversifiés » nous mettent tous long BTC en même temps. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def exposition_admissible(expositions_par_vault: Mapping[str, Any], *, equity: Any,
                          part_max: float = 0.5) -> dict[str, Any]:
    """Agrège |exposition| de tous les vaults sur le coin et la borne à part_max × equity. equity ≤ 0/inconnue →
    UNMEASURABLE. Retourne l'exposition agrégée, le plafond, et le facteur de réduction à appliquer si dépassement."""
    if not isinstance(equity, (int, float)) or float(equity) <= 0:
        return {"agregee": UNMEASURABLE, "refuse": True, "raison": "EQUITY_INVALIDE"}
    agregee = sum(abs(float(v)) for v in expositions_par_vault.values() if isinstance(v, (int, float)))
    plafond = float(part_max) * float(equity)
    depasse = agregee > plafond
    facteur = round(plafond / agregee, 8) if (depasse and agregee > 0) else 1.0
    return {"agregee": round(agregee, 8), "plafond": round(plafond, 8), "depasse": bool(depasse),
            "facteur_reduction": facteur, "refuse": False}


__all__ = ["exposition_admissible", "UNMEASURABLE"]
