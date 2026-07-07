"""Câblage: funding-arb + optimisations HL-Delta (APR gate, rotation, drift).

Compose apr_rotation (distillé HL-Delta) au-dessus du détecteur de paires funding.
Décide, pour un état de paires ouvertes + candidats, s'il faut entrer/tourner/
rééquilibrer/sortir — selon le rendement ANNUALISÉ, pas le bps/h brut. Flag-gated.
Pur; ne place jamais d'ordre (renvoie des décisions paper que le PaperEngine applique).
"""

from __future__ import annotations

import os

from hl_observer.funding.apr_rotation import (
    annualized_yield_pct, decide_rotation, delta_drift_action, passes_apr_gate,
)


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def optimize_funding_positions(
    *,
    current_coin: str | None,
    current_rate_bps_per_hour: float | None,
    candidate_rates: dict[str, float],       # coin -> rate bps/h disponible
    long_leg_usdt: float | None = None,
    short_leg_usdt: float | None = None,
    min_apr_pct: float = 5.0,
    switch_margin_apr_pct: float = 3.0,
    rebalance_threshold: float = 0.05,
) -> dict:
    """Décision funding-arb enrichie (flag HYPERSMART_FUNDING_ARB_APR_ROTATION)."""
    if not _on("HYPERSMART_FUNDING_ARB_APR_ROTATION"):
        return {"applied": False, "decision": "PASSTHROUGH", "reason": "APR_ROTATION_OFF"}

    rot = decide_rotation(
        current_coin=current_coin, current_rate_bps_per_hour=current_rate_bps_per_hour,
        candidates=candidate_rates, min_apr_pct=min_apr_pct, switch_margin_apr_pct=switch_margin_apr_pct,
    )
    out = {
        "applied": True,
        "decision": rot.action,
        "from_coin": rot.from_coin,
        "to_coin": rot.to_coin,
        "reason": rot.reason,
        "current_apr_pct": annualized_yield_pct(current_rate_bps_per_hour) if current_rate_bps_per_hour is not None else None,
        "paper_only": True, "real_execution": False,
    }
    # rebalance seulement si on tient une position à 2 jambes connues
    if rot.action == "HOLD" and long_leg_usdt is not None and short_leg_usdt is not None:
        drift = delta_drift_action(long_leg_usdt, short_leg_usdt, rebalance_threshold=rebalance_threshold)
        if drift["action"] == "REBALANCE":
            out["decision"] = "REBALANCE"
            out["reason"] = drift["reason"]
            out["drift_pct"] = drift["drift_pct"]
    return out


def rank_funding_candidates_by_apr(candidate_rates: dict[str, float], *, min_apr_pct: float = 5.0) -> list[dict]:
    """Classe les coins par APR décroissant, ne gardant que ceux au-dessus du gate."""
    rows = []
    for coin, rate in (candidate_rates or {}).items():
        if passes_apr_gate(rate, min_apr_pct=min_apr_pct):
            rows.append({"coin": str(coin).upper(), "apr_pct": annualized_yield_pct(rate), "rate_bps_per_hour": float(rate)})
    rows.sort(key=lambda r: -abs(r["apr_pct"]))
    return rows


__all__ = ["optimize_funding_positions", "rank_funding_candidates_by_apr"]
