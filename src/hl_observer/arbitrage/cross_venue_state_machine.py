"""P9.3 (§11.3) — machine à états du hedge cross-venue 2 jambes : leg-risk, résidu, unwind.

Un cross-venue n'est promouvable que si la SORTIE et la couverture sont exécutables. Cette machine
modélise le cycle :

    SIGNAL → LEG1_PENDING → LEG1_PARTIAL/FILLED → LEG2_HEDGE → HEDGED
    échec  : LEG2_FAIL → UNWIND (débouclage de la jambe 1 restée nue)

Elle publie ce qui compte pour juger le RISQUE de jambe : notionnel apparié, jambe résiduelle (nue),
latence de hedge, durée non couverte, slippage de hedge. Deny-by-default : une jambe 1 remplie mais
non couverte est un RISQUE explicite (résidu > 0), jamais ignorée ni supposée couverte au mid.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

SCHEMA_VERSION = "hypersmart.cross_venue_state_machine.v1"

# États / issues.
NO_LEG1 = "NO_LEG1"                       # rien n'est entré : pas de risque
HEDGED = "HEDGED"                         # jambe 1 entièrement couverte par la jambe 2
RESIDUAL_UNHEDGED = "RESIDUAL_UNHEDGED"   # couverture partielle : résidu nu (risque)
UNWIND_REQUIRED = "UNWIND_REQUIRED"       # jambe 2 a échoué : jambe 1 nue → débouclage requis

_TOL = 1e-9


def _num(x: object, defaut: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return defaut
    return v if math.isfinite(v) else defaut


def simuler_hedge(*, leg1: Mapping[str, Any], leg2: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Simule un cycle de hedge. `leg1`={notional_demande, notional_fill, ts_ms} ;
    `leg2`={notional_hedge, ts_ms, slippage_bps, echec, raison_echec} (ou None = jamais tenté)."""
    leg1 = leg1 or {}
    fill1 = max(0.0, _num(leg1.get("notional_fill")))
    demande1 = max(0.0, _num(leg1.get("notional_demande"), fill1))
    ts1 = leg1.get("ts_ms")

    if fill1 <= _TOL:
        return _resume(NO_LEG1, matched=0.0, residual=0.0, leg1_fill=0.0,
                       hedge_latency_ms=None, hedge_slippage_bps=None,
                       leg1_partial=(demande1 > _TOL), detail="jambe 1 non remplie")

    leg1_partial = fill1 + _TOL < demande1

    if leg2 is None or leg2.get("echec"):
        raison = (leg2 or {}).get("raison_echec") or "LEG2_NON_EXECUTEE"
        return _resume(UNWIND_REQUIRED, matched=0.0, residual=round(fill1, 10), leg1_fill=round(fill1, 10),
                       hedge_latency_ms=None, hedge_slippage_bps=None, leg1_partial=leg1_partial,
                       detail=f"jambe 1 nue ({raison}) → unwind")

    hedge = max(0.0, _num(leg2.get("notional_hedge")))
    matched = min(fill1, hedge)
    residual = max(0.0, fill1 - matched)
    ts2 = leg2.get("ts_ms")
    latence = None
    if ts1 is not None and ts2 is not None:
        d = _num(ts2) - _num(ts1)
        latence = round(d, 6) if d >= 0 else None      # horodatage incohérent → non mesuré
    slip = leg2.get("slippage_bps")
    slip = round(_num(slip), 6) if slip is not None else None

    issue = HEDGED if residual <= _TOL else RESIDUAL_UNHEDGED
    return _resume(issue, matched=round(matched, 10), residual=round(residual, 10),
                   leg1_fill=round(fill1, 10), hedge_latency_ms=latence, hedge_slippage_bps=slip,
                   leg1_partial=leg1_partial,
                   detail=("couvert" if issue == HEDGED else "résidu nu à déboucler"))


def _resume(issue, *, matched, residual, leg1_fill, hedge_latency_ms, hedge_slippage_bps,
            leg1_partial, detail) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": issue,
        "matched_notional_usd": matched,
        "residual_notional_usd": residual,      # jambe nue (risque)
        "leg1_fill_usd": leg1_fill,
        "leg1_partial": leg1_partial,
        "hedge_latency_ms": hedge_latency_ms,
        "hedge_slippage_bps": hedge_slippage_bps,
        "couvert": issue == HEDGED,
        "detail": detail,
        "real_execution": False,
    }


def statistiques_hedge(resumes) -> dict[str, Any]:
    """Agrège une population de hedges : taux d'échec, latence médiane, notionnel apparié/résiduel."""
    rs = [r for r in (resumes or []) if isinstance(r, Mapping)]
    tentes = [r for r in rs if r.get("issue") != NO_LEG1]
    n = len(tentes)
    echecs = sum(1 for r in tentes if r.get("issue") == UNWIND_REQUIRED)
    residuels = sum(1 for r in tentes if r.get("issue") == RESIDUAL_UNHEDGED)
    latences = sorted(r["hedge_latency_ms"] for r in tentes if r.get("hedge_latency_ms") is not None)
    med = None
    if latences:
        m = len(latences)
        med = latences[m // 2] if m % 2 else (latences[m // 2 - 1] + latences[m // 2]) / 2.0
    return {
        "schema_version": SCHEMA_VERSION,
        "n_hedges_tentes": n,
        "failed_hedge_rate": (round(echecs / n, 6) if n else None),
        "residual_rate": (round(residuels / n, 6) if n else None),
        "matched_notional_total_usd": round(sum(_num(r.get("matched_notional_usd")) for r in tentes), 6),
        "residual_notional_total_usd": round(sum(_num(r.get("residual_notional_usd")) for r in tentes), 6),
        "hedge_latency_mediane_ms": (round(med, 6) if med is not None else None),
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "NO_LEG1", "HEDGED", "RESIDUAL_UNHEDGED", "UNWIND_REQUIRED",
    "simuler_hedge", "statistiques_hedge",
]
