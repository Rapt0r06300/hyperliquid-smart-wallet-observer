"""AUD-134 — PnL EXPLORATOIRE n'est JAMAIS presente comme PnL VALIDE.

Le PnL des cohortes exploratoires (ALPHA, probes, experimental) est un PnL d'APPRENTISSAGE, pas un
PnL valide. Ce module etiquette tout PnL par tier et REFUSE de sommer exploratoire + valide (pas de
melange qui ferait passer de l'exploratoire pour du valide). Read-only, paper.
"""
from __future__ import annotations

TIER_VALIDE = "VALIDE"
TIER_EXPLORATOIRE = "EXPLORATOIRE"
_EXPLORATOIRES = frozenset({"alpha", "alpha_paper", "exploratory_paper", "discovery_probe",
                            "raw_probe", "experimental", "exploratoire"})


def tier_pnl(cohorte: str) -> str:
    return TIER_EXPLORATOIRE if str(cohorte).strip().lower() in _EXPLORATOIRES else TIER_VALIDE


def pnl_valide_seulement(pnls_par_cohorte: dict) -> dict:
    """Somme UNIQUEMENT le PnL VALIDE ; l'exploratoire est expose SEPAREMENT, jamais additionne."""
    valide = round(sum(float(v) for c, v in pnls_par_cohorte.items() if tier_pnl(c) == TIER_VALIDE), 8)
    explo = round(sum(float(v) for c, v in pnls_par_cohorte.items() if tier_pnl(c) == TIER_EXPLORATOIRE), 8)
    return {"pnl_valide": valide, "pnl_exploratoire_separe": explo, "melange_interdit": True,
            "detail": {c: {"pnl": float(v), "tier": tier_pnl(c)} for c, v in pnls_par_cohorte.items()}}


__all__ = ["tier_pnl", "pnl_valide_seulement", "TIER_VALIDE", "TIER_EXPLORATOIRE"]
