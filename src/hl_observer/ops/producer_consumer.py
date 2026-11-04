"""FIX-45 — PRODUCER / CONSUMER PAR STRATÉGIE.

`runtime_truth` (paper_canonique §7) décide, PAR stratégie active, si un producteur est vivant et la chaîne
(signal / moteur / ledger) prête. Seuls les événements des stratégies VIVANTES sont consommés par leur pipeline
canonique dédié (FIX-44, replay=forward). Une stratégie sans producteur vivant NE consomme RIEN — aucune activité
fabriquée, aucun fill fantôme.

But du FIX : `runtime_truth` n'est plus « jamais appelé » (un module jamais appelé = PAS DONE) — il PILOTE
désormais le routage réel producteur→consommateur. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import hashlib
import json

from hl_observer.ops.paper_canonique import STRATEGIES_ACTIVES, runtime_truth
from hl_observer.ops.paper_pipeline_e2e import PipelineCanonique


class ProducerConsumer:
    """Un consommateur (pipeline canonique) PAR stratégie active. Le routage est gouverné par `runtime_truth` :
    une stratégie n'ingère ses événements que si son producteur est déclaré VIVANT."""

    def __init__(self, **pipe_kw: Any) -> None:
        self._pipe_kw = dict(pipe_kw)
        self._consumers: dict[str, PipelineCanonique] = {s: PipelineCanonique(**pipe_kw) for s in STRATEGIES_ACTIVES}
        self.drops: dict[str, int] = {}
        self.rt_dernier: dict[str, Any] | None = None

    def _drop(self, raison: str) -> None:
        self.drops[raison] = self.drops.get(raison, 0) + 1

    def traiter(self, events: Sequence[Mapping[str, Any]], *, observations: Mapping[str, Mapping[str, Any]],
                now_ms: int, age_max_ms: float = 120_000.0) -> dict[str, Any]:
        """Route un lot d'événements selon la vérité runtime. Événement de marché (sans `strategy`) → tient
        l'état à jour des seules stratégies VIVANTES. Événement signalé → consommé si sa stratégie est VIVANTE,
        sinon DROP nommé (producteur absent / hors scope)."""
        rt = runtime_truth(observations, now_ms=now_ms, age_max_ms=age_max_ms)
        self.rt_dernier = rt
        etats = {s: l["etat"] for s, l in rt["strategies_actives"].items()}
        vivantes = {s for s, e in etats.items() if e == "VIVANT"}
        for e in events:
            strat = e.get("strategy")
            if strat is None:
                for s in vivantes:
                    self._consumers[s].consommer(e)
                continue
            if strat not in self._consumers:
                self._drop("HORS_SCOPE")
                continue
            if strat not in vivantes:
                self._drop("PRODUCTEUR_ABSENT:%s" % etats.get(strat, "?"))
                continue
            self._consumers[strat].consommer(e)
        return rt

    def scoreboards(self) -> dict[str, Any]:
        return {s: c.scoreboard() for s, c in self._consumers.items()}

    def consumer(self, strat: str) -> PipelineCanonique | None:
        return self._consumers.get(strat)


def golden_performance_receipt(*, baseline_ms: float, optimized_ms: float,
                               baseline_output: Any, optimized_output: Any) -> dict[str, Any]:
    """Prove measured speedup only when the golden output is byte-equivalent."""
    values = (baseline_ms, optimized_ms)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 for value in values):
        return {"status": "UNMEASURABLE", "reason": "timings_must_be_positive"}
    baseline_digest = hashlib.sha256(json.dumps(baseline_output, sort_keys=True, default=str).encode()).hexdigest()
    optimized_digest = hashlib.sha256(json.dumps(optimized_output, sort_keys=True, default=str).encode()).hexdigest()
    identical = baseline_digest == optimized_digest
    speedup = float(baseline_ms) / float(optimized_ms)
    return {"status": "PROVEN" if identical else "REJECTED", "baseline_ms": float(baseline_ms),
            "optimized_ms": float(optimized_ms), "speedup": round(speedup, 8),
            "golden_outputs_identical": identical, "semantic_drift": not identical,
            "automatic_activation": False}


__all__ = ["ProducerConsumer", "golden_performance_receipt"]
