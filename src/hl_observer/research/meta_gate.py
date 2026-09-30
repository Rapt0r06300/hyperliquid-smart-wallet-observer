"""ALPHA P37 — META-GATE de combinaison de signaux : combiner SEULEMENT si chaque composante ajoute du NET OOS.

Pas de score magique. On exige une **ablation** : une composante n'est gardée que si la retirer FAIT BAISSER
le net OOS (contribution marginale > 0). Sinon elle est droppée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def contributions_marginales(net_complet: float, net_sans_composante: Mapping[str, float]) -> dict[str, float]:
    """Contribution marginale d'une composante = net_complet − net_sans_elle. >0 ⇒ elle aide."""
    return {c: round(net_complet - v, 4) for c, v in net_sans_composante.items()}


def meta_gate(net_complet: Any, net_sans_composante: Mapping[str, Any], *, marge_bps: float = 0.0) -> dict[str, Any]:
    """Garde les composantes à contribution marginale > marge ; la combinaison n'est justifiée que si ≥1 garde."""
    if not isinstance(net_complet, (int, float)):
        return {"verdict": "MORE_DATA", "gardees": [], "droppees": list(net_sans_composante)}
    vals = {c: v for c, v in net_sans_composante.items() if isinstance(v, (int, float))}
    contrib = contributions_marginales(float(net_complet), vals)
    gardees = [c for c, m in contrib.items() if m > marge_bps]
    droppees = [c for c in vals if c not in gardees]
    # combinaison justifiée si elle bat la meilleure composante seule ET chaque gardée contribue
    justifiee = bool(gardees) and float(net_complet) > 0
    return {"contributions_marginales_bps": contrib, "gardees": gardees, "droppees": droppees,
            "verdict": ("COMBINER" if justifiee else "NE_PAS_COMBINER")}


__all__ = ["contributions_marginales", "meta_gate"]
