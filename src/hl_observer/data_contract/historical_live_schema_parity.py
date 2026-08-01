"""[DATA pépite 259] HISTORICAL/LIVE SCHEMA PARITY : le même objet canonique et les mêmes UNITÉS doivent
relier l'historique (backtest) et le forward (live). Si l'historique exprime un prix en ticks et le live en
dollars, ou si un champ existe d'un côté seulement, backtest et live divergent en silence — et l'edge mesuré
devient une illusion. On refuse la parité dès la moindre divergence de champ, type ou unité. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def comparer(schema_hist: dict[str, dict], schema_live: dict[str, dict]) -> dict[str, Any]:
    """Chaque schéma = {champ: {"type": ..., "unite": ...}}. Divergences : CHAMP_MANQUANT_LIVE,
    CHAMP_EN_TROP_LIVE, TYPE_DIFFERENT, UNITE_DIFFERENTE. Parité vraie seulement si zéro divergence."""
    if not isinstance(schema_hist, dict) or not isinstance(schema_live, dict):
        return {"parite": False, "divergences": [{"raison": "SCHEMA_INVALIDE"}]}
    divergences: list[dict[str, Any]] = []
    for champ, spec_h in schema_hist.items():
        if champ not in schema_live:
            divergences.append({"champ": champ, "raison": "CHAMP_MANQUANT_LIVE"})
            continue
        spec_l = schema_live[champ]
        if spec_h.get("type") != spec_l.get("type"):
            divergences.append({"champ": champ, "raison": "TYPE_DIFFERENT",
                                "hist": spec_h.get("type"), "live": spec_l.get("type")})
        if spec_h.get("unite") != spec_l.get("unite"):
            divergences.append({"champ": champ, "raison": "UNITE_DIFFERENTE",
                                "hist": spec_h.get("unite"), "live": spec_l.get("unite")})
    for champ in schema_live:
        if champ not in schema_hist:
            divergences.append({"champ": champ, "raison": "CHAMP_EN_TROP_LIVE"})
    parite = len(divergences) == 0
    return {"parite": parite, "divergences": divergences}


__all__ = ["comparer"]
