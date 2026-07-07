"""P6 — Gate d'éligibilité testnet: reste VERROUILLÉ tant que le paper n'a pas fait ses preuves.

Le squelette d'exécution testnet existe et est fail-closed (TestnetSafetyGuard). Ce
gate est la décision AMONT: a-t-on le DROIT d'envisager le testnet ? Conditions du
cap produit (CLAUDE.md addendum): PF net paper > seuil, STABLE sur N jours, drawdown
contenu, audit sécurité vert, échantillon suffisant. Deny-by-default: au moindre
doute → NOT_READY. Pur, aucune activation ici (il décrit seulement l'éligibilité).
"""

from __future__ import annotations

from statistics import mean


def evaluate_testnet_readiness(
    daily_profit_factors: list[float],
    *,
    min_pf: float = 1.0,
    min_days_stable: int = 14,
    max_drawdown_usdc: float = 20.0,
    observed_max_drawdown_usdc: float | None = None,
    safety_audit_green: bool = False,
    min_closed_trades: int = 100,
    closed_trades: int = 0,
) -> dict:
    """Retourne l'éligibilité (jamais l'activation). READY exige TOUTES les conditions."""

    reasons: list[str] = []
    pfs = [float(x) for x in (daily_profit_factors or []) if _num(x)]

    if len(pfs) < int(min_days_stable):
        reasons.append(f"NOT_ENOUGH_STABLE_DAYS ({len(pfs)}/{min_days_stable})")
    days_below = sum(1 for x in pfs if x < min_pf)
    if days_below > 0:
        reasons.append(f"PF_BELOW_1_ON_{days_below}_DAYS")
    if pfs and mean(pfs) < min_pf:
        reasons.append("MEAN_PF_BELOW_MIN")
    if not safety_audit_green:
        reasons.append("SAFETY_AUDIT_NOT_GREEN")
    if int(closed_trades) < int(min_closed_trades):
        reasons.append(f"INSUFFICIENT_SAMPLE ({closed_trades}/{min_closed_trades})")
    if observed_max_drawdown_usdc is not None and abs(float(observed_max_drawdown_usdc)) > max_drawdown_usdc:
        reasons.append("DRAWDOWN_EXCEEDS_LIMIT")

    ready = not reasons
    return {
        "testnet_eligible": ready,
        "verdict": "READY_FOR_TESTNET_REVIEW" if ready else "NOT_READY_STAY_PAPER",
        "reasons": reasons if reasons else ["ALL_GATES_PASSED"],
        "mean_pf": round(mean(pfs), 4) if pfs else None,
        "days_evaluated": len(pfs),
        "note": "éligibilité seulement; l'exécution reste fail-closed via TestnetSafetyGuard; jamais mainnet",
    }


def _num(x) -> bool:
    try:
        float(x); return True
    except (TypeError, ValueError):
        return False


__all__ = ["evaluate_testnet_readiness"]
