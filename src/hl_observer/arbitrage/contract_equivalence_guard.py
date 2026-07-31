"""[ARB #9] CONTRACT-EQUIVALENCE GUARD : vérifier que deux symboles représentent VRAIMENT le même
sous-jacent/contrat AVANT de comparer leurs prix. Même sous-jacent (via le registre d'équivalence #8), même
type (perp/spot/future), même multiplicateur, même expiry, même quote. La moindre divergence = REFUS (comparer
leurs prix serait un faux arbitrage). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.arbitrage.asset_equivalence_registry import RegistreEquivalence


def contrats_equivalents(a: Mapping[str, Any], b: Mapping[str, Any], *,
                         registre: RegistreEquivalence | None = None) -> dict[str, Any]:
    """`a`,`b` = {underlying, type, multiplier?, expiry?, quote?}. Équivalents seulement si TOUT concorde.
    Divergences listées explicitement ; un champ requis manquant rend l'équivalence indéterminée (refus)."""
    reg = registre or RegistreEquivalence()
    divergences = []
    ua, ub = reg.canonique(a.get("underlying")), reg.canonique(b.get("underlying"))
    if ua is None or ub is None or ua != ub:
        divergences.append("underlying")
    if str(a.get("type", "")).upper() != str(b.get("type", "")).upper() or not a.get("type"):
        divergences.append("type")
    if float(a.get("multiplier", 1.0)) != float(b.get("multiplier", 1.0)):
        divergences.append("multiplier")
    if a.get("expiry") != b.get("expiry"):
        divergences.append("expiry")
    if str(a.get("quote", "")).upper() != str(b.get("quote", "")).upper():
        divergences.append("quote")
    return {"equivalents": (not divergences), "divergences": divergences,
            "underlying_canonique": (ua if ua == ub else None)}


__all__ = ["contrats_equivalents"]
