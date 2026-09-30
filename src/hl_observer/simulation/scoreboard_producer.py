"""Câblage-2 — PRODUCTEUR runtime du scoreboard : accumule les observations d'exécution par stratégie,
puis produit le scoreboard réconcilié sur le ledger LIVE.

Chaîne : (run paper) → `ScoreboardProducer.observer_*` accumule coûts décomposés, latences réelles, fill
ratios, résumés de hedge par stratégie → `scoreboard_runtime_metrics` agrège (avec UNMEASURABLE strict)
→ `scoreboard_feeder` assemble la ligne par stratégie depuis le ledger scellé + évalue la promotion.

C'est le chaînon manquant entre le moteur vivant et le scoreboard : le moteur n'a qu'à appeler
`observer_fill` / `observer_hedge` / `fixer_mesures` au fil de l'eau, puis `produire(ledger)`. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.simulation import scoreboard_feeder as _feeder
from hl_observer.simulation import scoreboard_runtime_metrics as _rm

SCHEMA_VERSION = "hypersmart.scoreboard_producer.v1"

_SCALAIRES = ("gross_edge_bps", "capacity_usd", "oos_net_bps", "forward_net_bps", "roi_denominator_usd")


class ScoreboardProducer:
    """Accumulateur d'observations runtime par stratégie → scoreboard réconcilié."""

    def __init__(self) -> None:
        self._obs: dict[str, dict[str, Any]] = {}

    def _cell(self, strategy: str) -> dict[str, Any]:
        return self._obs.setdefault(str(strategy), {
            "couts_par_fill": [], "latences_ms": [], "fill_ratios": [], "hedge_resumes": [], "scalaires": {},
        })

    def observer_fill(self, strategy: str, *, cost_components: Mapping[str, Any] | None = None,
                      latency_ms: float | None = None, fill_ratio: float | None = None) -> None:
        """Un fill exécuté : coûts décomposés (cost_components), latence réelle, ratio de remplissage."""
        c = self._cell(strategy)
        if cost_components is not None:
            c["couts_par_fill"].append(dict(cost_components))
        if latency_ms is not None:
            c["latences_ms"].append(latency_ms)
        if fill_ratio is not None:
            c["fill_ratios"].append(fill_ratio)

    def observer_hedge(self, strategy: str, resume: Mapping[str, Any]) -> None:
        """Un résumé de hedge cross-venue (sortie de `cross_venue_state_machine.simuler_hedge`)."""
        self._cell(strategy)["hedge_resumes"].append(dict(resume))

    def fixer_mesures(self, strategy: str, **scalaires: Any) -> None:
        """Fixe les scalaires par stratégie : gross_edge_bps, capacity_usd, oos_net_bps, forward_net_bps, roi_denominator_usd."""
        c = self._cell(strategy)["scalaires"]
        for k, v in scalaires.items():
            if k in _SCALAIRES and v is not None:
                c[k] = v

    def observations(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for strat, c in self._obs.items():
            out[strat] = {
                **c["scalaires"],
                "couts_par_fill": list(c["couts_par_fill"]),
                "latences_ms": list(c["latences_ms"]),
                "fill_ratios": list(c["fill_ratios"]),
                "hedge_resumes": list(c["hedge_resumes"]),
            }
        return out

    def produire(
        self,
        ledger_events: Sequence[Mapping[str, Any]],
        *,
        snapshot: Mapping[str, Any] | None = None,
        strategies_attendues: Sequence[str] | None = None,
        evidence_par_strategie: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produit le scoreboard : mesures runtime agrégées → feeder sur le ledger scellé + promotion."""
        paquet = _rm.mesures_par_strategie(self.observations())
        res = _feeder.lignes_depuis_ledger(
            ledger_events, snapshot=snapshot, strategies_attendues=strategies_attendues,
            mesures_par_strategie=paquet["mesures_par_strategie"],
            evidence_par_strategie=evidence_par_strategie,
        )
        d = res.to_dict()
        d["metriques_runtime_par_strategie"] = paquet["metriques_runtime_par_strategie"]
        d["schema_version_producer"] = SCHEMA_VERSION
        return d


__all__ = ["SCHEMA_VERSION", "ScoreboardProducer"]
