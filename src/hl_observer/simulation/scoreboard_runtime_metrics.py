"""P1B/P2 — assemble les MESURES runtime par stratégie pour `scoreboard_feeder` (P2.3).

Le feeder accepte `mesures_par_strategie` ; il fallait le PRODUCTEUR qui transforme les observations
runtime (coûts décomposés par fill, latences réelles, fill ratios, capacité, résumés de hedge P9.3) en
ces mesures. Chaque métrique ABSENTE reste `UNMEASURABLE` (None) — jamais un 0 fabriqué. Sont produits :
coûts (fees/spread/slippage/latence bps), capacity, fill_ratio, latence p50/p95/p99, et — pour le
cross-venue — hedge latency, residual exposure, unwind PnL, failed hedge rate (via `statistiques_hedge`).

Composé, pur, 0 réseau, 0 ordre réel. Sortie : `{"mesures": {...pour le feeder}, "metriques_runtime":
{...extras reçus par le scoreboard}, "unmeasured": [...]}`.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.arbitrage.cross_venue_state_machine import statistiques_hedge

SCHEMA_VERSION = "hypersmart.scoreboard_runtime_metrics.v1"

_COMPOSANTES = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")


def _num(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _moyenne(vals: Sequence[float]) -> float | None:
    v = [x for x in (_num(u) for u in vals) if x is not None]
    return round(sum(v) / len(v), 6) if v else None


def percentiles(valeurs: Sequence[float], qs: Sequence[float] = (0.5, 0.95, 0.99)) -> dict[float, float | None]:
    """Percentiles nearest-rank. `None` par quantile si la série est vide (jamais fabriqué)."""
    v = sorted(x for x in (_num(u) for u in valeurs) if x is not None)
    out: dict[float, float | None] = {}
    n = len(v)
    for q in qs:
        if n == 0:
            out[q] = None
        else:
            idx = min(n - 1, max(0, int(math.ceil(q * n)) - 1))
            out[q] = round(v[idx], 6)
    return out


def _cout_moyen(couts_par_fill: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Moyenne de chaque composante de coût sur les fills qui la portent ; None si aucune ne la porte."""
    out: dict[str, float | None] = {}
    for c in _COMPOSANTES:
        vals = [_num(f.get(c)) for f in couts_par_fill]
        vals = [x for x in vals if x is not None]
        out[c] = round(sum(vals) / len(vals), 6) if vals else None
    return out


def agreger_mesures_strategie(
    *,
    couts_par_fill: Sequence[Mapping[str, Any]] | None = None,
    latences_ms: Sequence[float] | None = None,
    fill_ratios: Sequence[float] | None = None,
    capacity_usd: float | None = None,
    gross_edge_bps: float | None = None,
    oos_net_bps: float | None = None,
    forward_net_bps: float | None = None,
    roi_denominator_usd: float | None = None,
    hedge_resumes: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Transforme les observations runtime d'UNE stratégie en mesures pour le scoreboard. Absent ⇒ UNMEASURABLE."""
    couts = _cout_moyen(list(couts_par_fill or []))
    pct = percentiles(list(latences_ms or []))
    fr_moy = _moyenne(list(fill_ratios or []))

    mesures: dict[str, Any] = {
        "gross_edge_bps": _num(gross_edge_bps),
        "fees_bps": couts["fees_bps"], "spread_bps": couts["spread_bps"],
        "slippage_bps": couts["slippage_bps"], "latency_bps": couts["latency_bps"],
        "capacity_usd": _num(capacity_usd),
        "fill_ratios": ([fr_moy] if fr_moy is not None else None),
        "latency_p50_ms": pct[0.5], "latency_p95_ms": pct[0.95],
        "oos_net_bps": _num(oos_net_bps), "forward_net_bps": _num(forward_net_bps),
        "roi_denominator_usd": _num(roi_denominator_usd),
    }

    hedge = statistiques_hedge(list(hedge_resumes or [])) if hedge_resumes else None
    metriques_runtime: dict[str, Any] = {
        "latency_p99_ms": pct[0.99],
        "hedge_latency_mediane_ms": (hedge.get("hedge_latency_mediane_ms") if hedge else None),
        "residual_exposure_total_usd": (hedge.get("residual_exposure_total_usd") if hedge else None),
        "unwind_net_pnl_total_usd": (hedge.get("unwind_net_pnl_total_usd") if hedge else None),
        "failed_hedge_rate": (hedge.get("failed_hedge_rate") if hedge else None),
    }

    unmeasured = [k for k, v in {**mesures, **metriques_runtime}.items() if v is None]
    return {
        "schema_version": SCHEMA_VERSION,
        "mesures": {k: v for k, v in mesures.items() if v is not None},   # le feeder ignore les None
        "metriques_runtime": metriques_runtime,
        "unmeasured": unmeasured,
        "real_execution": False,
    }


def mesures_par_strategie(observations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Agrège plusieurs stratégies : `{strategy: kwargs_observations}` → prêt pour scoreboard_feeder + extras."""
    mesures: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for strat, obs in (observations or {}).items():
        agr = agreger_mesures_strategie(**dict(obs))
        mesures[strat] = agr["mesures"]
        extras[strat] = agr["metriques_runtime"]
    return {"schema_version": SCHEMA_VERSION, "mesures_par_strategie": mesures,
            "metriques_runtime_par_strategie": extras, "real_execution": False}


__all__ = [
    "SCHEMA_VERSION", "percentiles", "agreger_mesures_strategie", "mesures_par_strategie",
]
