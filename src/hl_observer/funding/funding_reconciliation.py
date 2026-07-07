"""P2 — Réconciliation funding réel vs prédit + détection de dérive.

Le funding-arb paper crédite des accruals PRÉDITS. Ce module les confronte aux
paiements RÉELS observés (funding_poller / snapshots) pour: (1) mesurer l'erreur
de prédiction, (2) détecter une dérive du taux (le rate a chuté/s'est inversé →
sortir), (3) alerter si l'écart cumulé dépasse un seuil (modèle à recalibrer).
Pur, honnête: sans paiement réel observé, on ne réconcilie pas (INSUFFICIENT).
"""

from __future__ import annotations


def reconcile_funding(predicted: list[dict], actual: list[dict], *, pair_key: str = "pair_id") -> dict:
    """Apparie prédits et réels par pair_id, calcule l'erreur par paire et globale."""

    pred_by = {}
    for p in predicted or []:
        if isinstance(p, dict) and p.get(pair_key):
            pred_by[str(p[pair_key])] = pred_by.get(str(p[pair_key]), 0.0) + float(p.get("amount_usdc") or 0.0)
    act_by = {}
    for a in actual or []:
        if isinstance(a, dict) and a.get(pair_key):
            act_by[str(a[pair_key])] = act_by.get(str(a[pair_key]), 0.0) + float(a.get("amount_usdc") or 0.0)
    if not act_by:
        return {"status": "INSUFFICIENT_ACTUAL_PAYMENTS", "pairs": 0}

    rows = []
    total_pred = total_act = total_abs_err = 0.0
    for pid in sorted(set(pred_by) | set(act_by)):
        pr, ac = pred_by.get(pid, 0.0), act_by.get(pid, 0.0)
        err = ac - pr
        rows.append({"pair_id": pid, "predicted_usdc": round(pr, 6),
                     "actual_usdc": round(ac, 6), "error_usdc": round(err, 6)})
        total_pred += pr; total_act += ac; total_abs_err += abs(err)
    mape = (total_abs_err / abs(total_pred)) if total_pred else None
    return {
        "status": "OK",
        "pairs": len(rows),
        "total_predicted_usdc": round(total_pred, 6),
        "total_actual_usdc": round(total_act, 6),
        "total_abs_error_usdc": round(total_abs_err, 6),
        "mean_abs_pct_error": round(mape, 4) if mape is not None else None,
        "rows": rows,
        "honesty": "erreur descriptive; pas de promesse; recalibrer si l'erreur dérive",
    }


def funding_drift_exit(entry_rate_bps_per_hour: float, current_rate_bps_per_hour: float,
                       *, exit_edge_bps_per_hour: float = 0.65, reversal_guard: bool = True) -> dict:
    """Faut-il sortir la paire ? (edge effondré ou funding inversé)."""
    entry = float(entry_rate_bps_per_hour)
    cur = float(current_rate_bps_per_hour)
    # inversion de signe = le vent a tourné, on ne reçoit plus, on paie
    if reversal_guard and entry != 0 and (entry > 0) != (cur > 0) and cur != 0:
        return {"exit": True, "reason": "FUNDING_REVERSED"}
    if abs(cur) < float(exit_edge_bps_per_hour):
        return {"exit": True, "reason": "FUNDING_EDGE_COLLAPSED"}
    return {"exit": False, "reason": "FUNDING_STILL_PAYS"}


def cumulative_drift_alert(reconciliation: dict, *, max_abs_error_usdc: float = 0.5, max_mape: float = 0.5) -> dict:
    """Alerte si le modèle de funding dérive trop du réel (à recalibrer)."""
    if not isinstance(reconciliation, dict) or reconciliation.get("status") != "OK":
        return {"alert": False, "reason": "NO_RECONCILIATION"}
    err = float(reconciliation.get("total_abs_error_usdc") or 0.0)
    mape = reconciliation.get("mean_abs_pct_error")
    if err > max_abs_error_usdc or (mape is not None and mape > max_mape):
        return {"alert": True, "reason": "FUNDING_MODEL_DRIFT", "abs_error_usdc": err, "mape": mape}
    return {"alert": False, "reason": "WITHIN_TOLERANCE", "abs_error_usdc": err, "mape": mape}


__all__ = ["reconcile_funding", "funding_drift_exit", "cumulative_drift_alert"]
