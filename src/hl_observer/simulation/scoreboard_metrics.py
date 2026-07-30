"""Jalon 1 — assembleur de la ligne de SCOREBOARD réconciliée (pur, 0 réseau, 0 ordre réel).

Les briques PnL/ROI/equity existent (`capital_accounting` pour ROI/equity/turnover/exposure,
`log_metrics` pour PF_net à partir des logs) mais AUCUN module ne réunit la ligne complète exigée
pour juger une stratégie, avec une comptabilité honnête des manques :

    strategy | N_indep | gross_edge_bps | costs_bps | net_bps | PnL | ROI | PF | DD | ES | hit |
    capacity | fill_ratio | latency_p50_ms | latency_p95_ms | OOS | forward | verdict

**Règle DURE, non négociable :** toute composante dont l'entrée est absente vaut `UNMEASURABLE`
(`None`), JAMAIS `0`. Un `net_bps` calculé en oubliant un coût est un FAUX edge. `costs_bps`
n'existe que si TOUTES ses composantes (fees, spread, slippage, latency) sont mesurées ; sinon
`UNMEASURABLE`, et `net_bps` l'est aussi. Ce module MESURE ; le verdict `PROMOTE` n'est rendu que si
l'edge net **ET** l'OOS **ET** le forward sont positifs avec un N indépendant suffisant — sinon
`KILL` (négatif prouvé) ou `MORE_DATA`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

SCHEMA_VERSION = "hypersmart.scoreboard_metrics.v1"

#: Composantes de coût qui doivent TOUTES être mesurées pour qu'un `costs_bps` existe.
COMPOSANTES_COUT = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")

#: N d'événements INDÉPENDANTS minimum pour oser un verdict positif (pas 1 fill = 1 obs).
N_INDEP_MIN_PROMOTE = 20


def _fini(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def profit_factor(pnls: Sequence[float]) -> float | None:
    """Σ gains / Σ|pertes|. `None` (UNMEASURABLE) si aucun trade OU aucune perte (ratio non défini).

    On ne renvoie ni `0` ni un sentinelle `999` : sans perte, le profit factor n'est pas estimable,
    le dire est plus honnête que d'inventer un grand nombre.
    """
    vals = [float(p) for p in pnls if _fini(p)]
    if not vals:
        return None
    gains = sum(p for p in vals if p > 0)
    pertes = -sum(p for p in vals if p < 0)
    if pertes <= 0:
        return None
    return round(gains / pertes, 6)


def max_drawdown(pnls: Sequence[float]) -> float | None:
    """Drawdown maximal (nombre ≥ 0) de la courbe cumulée des PnL clos. `None` si vide."""
    vals = [float(p) for p in pnls if _fini(p)]
    if not vals:
        return None
    cumul = 0.0
    sommet = 0.0
    dd = 0.0
    for p in vals:
        cumul += p
        sommet = max(sommet, cumul)
        dd = max(dd, sommet - cumul)
    return round(dd, 6)


def expected_shortfall(pnls: Sequence[float], q: float = 0.05) -> float | None:
    """Expected shortfall = moyenne des `q` pires PnL (perte moyenne dans la queue). `None` si trop peu.

    Rendu comme un nombre signé (négatif = perte moyenne de queue). `None` si la queue serait vide.
    """
    vals = sorted(float(p) for p in pnls if _fini(p))
    if not vals:
        return None
    k = max(1, int(math.ceil(len(vals) * float(q))))
    if k > len(vals):
        return None
    pires = vals[:k]
    return round(sum(pires) / len(pires), 6)


def hit_rate(pnls: Sequence[float]) -> float | None:
    """Fraction de trades clos strictement gagnants. `None` si aucun trade."""
    vals = [float(p) for p in pnls if _fini(p)]
    if not vals:
        return None
    return round(sum(1 for p in vals if p > 0) / len(vals), 6)


def costs_bps(fees_bps=None, spread_bps=None, slippage_bps=None, latency_bps=None) -> float | None:
    """Somme des coûts bps SEULEMENT si toutes les composantes sont mesurées ; sinon `None`.

    Ne jamais compléter une composante absente par 0 : un coût oublié gonfle le net.
    """
    comps = (fees_bps, spread_bps, slippage_bps, latency_bps)
    if any(c is None or not _fini(c) for c in comps):
        return None
    return round(sum(float(c) for c in comps), 6)


@dataclass(frozen=True, slots=True)
class ScoreboardRow:
    strategy: str
    n_independent: int | None
    gross_edge_bps: float | None
    costs_bps: float | None
    net_bps: float | None
    pnl_usd: float | None
    roi: float | None
    profit_factor: float | None
    max_drawdown_usd: float | None
    expected_shortfall_usd: float | None
    hit_rate: float | None
    capacity_usd: float | None
    fill_ratio: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    oos_net_bps: float | None
    forward_net_bps: float | None
    verdict: str
    unmeasured: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["unmeasured"] = list(self.unmeasured)
        d["schema_version"] = SCHEMA_VERSION
        d["paper_only"] = True
        d["real_execution"] = False
        return d


def _moyenne(fill_ratios):
    vals = [float(x) for x in (fill_ratios or []) if _fini(x)]
    return round(sum(vals) / len(vals), 6) if vals else None


def assembler_ligne(
    strategy: str,
    *,
    closed_pnls: Sequence[float] | None = None,
    n_independent: int | None = None,
    gross_edge_bps: float | None = None,
    fees_bps: float | None = None,
    spread_bps: float | None = None,
    slippage_bps: float | None = None,
    latency_bps: float | None = None,
    roi_denominator_usd: float | None = None,
    capacity_usd: float | None = None,
    fill_ratios: Sequence[float] | None = None,
    latency_p50_ms: float | None = None,
    latency_p95_ms: float | None = None,
    oos_net_bps: float | None = None,
    forward_net_bps: float | None = None,
) -> ScoreboardRow:
    """Assemble la ligne de scoreboard réconciliée. Toute entrée absente reste `UNMEASURABLE`."""
    pnls = [float(p) for p in (closed_pnls or []) if _fini(p)]
    pnl = round(sum(pnls), 6) if pnls else None
    ct = costs_bps(fees_bps, spread_bps, slippage_bps, latency_bps)
    net = (round(float(gross_edge_bps) - ct, 6)
           if (gross_edge_bps is not None and _fini(gross_edge_bps) and ct is not None) else None)
    roi = (round(pnl / float(roi_denominator_usd), 6)
           if (pnl is not None and roi_denominator_usd not in (None, 0) and _fini(roi_denominator_usd)
               and float(roi_denominator_usd) > 0) else None)
    pf = profit_factor(pnls)
    dd = max_drawdown(pnls)
    es = expected_shortfall(pnls)
    hit = hit_rate(pnls)
    fr = _moyenne(fill_ratios)

    # Verdict conservateur, deny-by-default.
    positifs_requis = (net, oos_net_bps, forward_net_bps)
    if all(v is not None and _fini(v) for v in positifs_requis) and n_independent is not None:
        if all(float(v) > 0 for v in positifs_requis) and int(n_independent) >= N_INDEP_MIN_PROMOTE:
            verdict = "PROMOTE"
        elif any(float(v) < 0 for v in positifs_requis):
            verdict = "KILL"
        else:
            verdict = "MORE_DATA"
    elif net is not None and _fini(net) and float(net) < 0:
        verdict = "KILL"                      # net prouvé négatif : inutile d'attendre l'OOS
    else:
        verdict = "MORE_DATA"                 # au moins une brique décisive est UNMEASURABLE

    champs = {
        "n_independent": n_independent, "gross_edge_bps": gross_edge_bps, "costs_bps": ct,
        "net_bps": net, "pnl_usd": pnl, "roi": roi, "profit_factor": pf,
        "max_drawdown_usd": dd, "expected_shortfall_usd": es, "hit_rate": hit,
        "capacity_usd": capacity_usd, "fill_ratio": fr,
        "latency_p50_ms": latency_p50_ms, "latency_p95_ms": latency_p95_ms,
        "oos_net_bps": oos_net_bps, "forward_net_bps": forward_net_bps,
    }
    unmeasured = tuple(k for k, v in champs.items() if v is None)

    return ScoreboardRow(
        strategy=str(strategy),
        n_independent=(int(n_independent) if n_independent is not None else None),
        gross_edge_bps=(round(float(gross_edge_bps), 6) if gross_edge_bps is not None and _fini(gross_edge_bps) else None),
        costs_bps=ct, net_bps=net, pnl_usd=pnl, roi=roi, profit_factor=pf,
        max_drawdown_usd=dd, expected_shortfall_usd=es, hit_rate=hit,
        capacity_usd=(round(float(capacity_usd), 6) if capacity_usd is not None and _fini(capacity_usd) else None),
        fill_ratio=fr,
        latency_p50_ms=(round(float(latency_p50_ms), 6) if latency_p50_ms is not None and _fini(latency_p50_ms) else None),
        latency_p95_ms=(round(float(latency_p95_ms), 6) if latency_p95_ms is not None and _fini(latency_p95_ms) else None),
        oos_net_bps=(round(float(oos_net_bps), 6) if oos_net_bps is not None and _fini(oos_net_bps) else None),
        forward_net_bps=(round(float(forward_net_bps), 6) if forward_net_bps is not None and _fini(forward_net_bps) else None),
        verdict=verdict, unmeasured=unmeasured,
    )


__all__ = [
    "SCHEMA_VERSION", "COMPOSANTES_COUT", "N_INDEP_MIN_PROMOTE",
    "profit_factor", "max_drawdown", "expected_shortfall", "hit_rate", "costs_bps",
    "ScoreboardRow", "assembler_ligne",
]
