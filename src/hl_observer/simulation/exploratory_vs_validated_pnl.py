"""AUD-134 — PnL EXPLORATOIRE n'est JAMAIS presente comme PnL VALIDE.

Le PnL des cohortes exploratoires (ALPHA, probes, experimental) est un PnL d'APPRENTISSAGE, pas un
PnL valide. Ce module etiquette tout PnL par tier et REFUSE de sommer exploratoire + valide (pas de
melange qui ferait passer de l'exploratoire pour du valide). Read-only, paper.
"""
from __future__ import annotations

TIER_VALIDE = "VALIDE"
TIER_EXPLORATOIRE = "EXPLORATOIRE"
TIER_TRAIN = "TRAIN_EXPLORATOIRE"
TIER_SHADOW = "SHADOW_PAPER"
TIER_REPLAY = "REPLAY_PAPER"
TIER_FORWARD = "FORWARD_PAPER"
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


def label_pnl_stage(
    stage: str,
    *,
    post_freeze: bool = False,
    economic_certified: bool = False,
) -> dict[str, object]:
    """Label a PnL display without promoting TRAIN or unverified forward."""
    normalized = str(stage or "").strip().lower()
    if normalized == "train":
        return {
            "tier": TIER_TRAIN,
            "is_paper": True,
            "forward_certified": False,
            "status": "EXPLORATORY_ONLY",
            "reason": "TRAIN_CANNOT_BE_FORWARD_CERTIFIED",
        }
    if normalized == "shadow":
        return {
            "tier": TIER_SHADOW,
            "is_paper": True,
            "forward_certified": False,
            "status": "PAPER_ONLY",
            "reason": None,
        }
    if normalized == "replay":
        return {
            "tier": TIER_REPLAY,
            "is_paper": True,
            "forward_certified": False,
            "status": "PAPER_ONLY",
            "reason": None,
        }
    if normalized == "forward":
        if not post_freeze:
            return {
                "tier": TIER_FORWARD,
                "is_paper": True,
                "forward_certified": False,
                "status": "UNMEASURABLE",
                "reason": "FORWARD_NOT_POST_FREEZE",
            }
        if not economic_certified:
            return {
                "tier": TIER_FORWARD,
                "is_paper": True,
                "forward_certified": False,
                "status": "PAPER_UNVERIFIED",
                "reason": "FORWARD_ECONOMIC_CERTIFICATION_MISSING",
            }
        return {
            "tier": TIER_FORWARD,
            "is_paper": True,
            "forward_certified": True,
            "status": "PAPER_VERIFIED",
            "reason": None,
        }
    return {
        "tier": TIER_EXPLORATOIRE,
        "is_paper": True,
        "forward_certified": False,
        "status": "UNMEASURABLE",
        "reason": "UNKNOWN_PNL_STAGE",
    }


__all__ = [
    "tier_pnl", "pnl_valide_seulement", "label_pnl_stage",
    "TIER_VALIDE", "TIER_EXPLORATOIRE", "TIER_TRAIN", "TIER_SHADOW",
    "TIER_REPLAY", "TIER_FORWARD",
]
