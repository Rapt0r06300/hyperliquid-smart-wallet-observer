"""[COPY-VAULT #81] ATTRIBUTION AFTER NETTING : malgré le netting (#80), conserver quelle FRACTION du PnL revient à
chaque vault. Le trade net est unique, mais chaque vault y a contribué ; on répartit le PnL au prorata des
contributions BRUTES (|montant| de chaque vault), pas au prorata du net. Sans ça, le netting effacerait
l'attribution par vault. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def attribuer(contributions: Mapping[str, Any], pnl_total: Any) -> dict[str, Any]:
    """Répartit `pnl_total` entre vaults au prorata de |contribution|. Somme des |contributions| nulle ou PnL
    invalide → UNMEASURABLE (on n'invente pas une répartition)."""
    if not isinstance(pnl_total, (int, float)):
        return {"parts": UNMEASURABLE, "raison": "PNL_INVALIDE"}
    poids = {str(v): abs(float(m)) for v, m in contributions.items() if isinstance(m, (int, float))}
    somme = sum(poids.values())
    if somme <= 0:
        return {"parts": UNMEASURABLE, "raison": "CONTRIBUTIONS_NULLES"}
    parts = {v: round(float(pnl_total) * (p / somme), 8) for v, p in poids.items()}
    return {"parts": parts, "controle_somme": round(sum(parts.values()), 6)}


__all__ = ["attribuer", "UNMEASURABLE"]
