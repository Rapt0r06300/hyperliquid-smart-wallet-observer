"""ALPHA P12 — RECETTE économique : 4 scénarios de coût. OPTIMISTIC ne PROMOTE jamais.

Chaque idée est jugée sous plusieurs régimes de coût, pour ne garder que ce qui survit à l'adverse :
  * BASE_CALIBRATED         — coûts calibrés réalistes (référence de décision) ;
  * ADVERSE_P95 / ADVERSE_P99 — coûts stressés (slippage/latence au P95/P99) ;
  * OPTIMISTIC_DIAGNOSTIC_ONLY — borne haute, DIAGNOSTIC seulement, **ne peut jamais promouvoir**.

Un PROMOTE exige de survivre au moins jusqu'à ADVERSE_P95. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"

#: multiplicateur de coût + add-on slippage (bps) par scénario.
SCENARIOS: dict[str, dict[str, float]] = {
    "OPTIMISTIC_DIAGNOSTIC_ONLY": {"mult": 0.7, "slippage_add_bps": 0.0},
    "BASE_CALIBRATED": {"mult": 1.0, "slippage_add_bps": 0.5},
    "ADVERSE_P95": {"mult": 1.0, "slippage_add_bps": 2.0},
    "ADVERSE_P99": {"mult": 1.0, "slippage_add_bps": 4.0},
}

#: scénarios autorisés à PROMOTE (l'optimiste est exclu par construction).
SCENARIOS_PROMOTE = ("BASE_CALIBRATED", "ADVERSE_P95", "ADVERSE_P99")


def peut_promote(scenario: str) -> bool:
    """OPTIMISTIC ne PROMOTE jamais."""
    return scenario in SCENARIOS_PROMOTE


def net_sous_scenario(gross_bps: float, cost_base_bps: float, scenario: str) -> float:
    """Net = gross − (coût_base × mult + slippage_add) du scénario."""
    s = SCENARIOS[scenario]
    cout = cost_base_bps * s["mult"] + s["slippage_add_bps"]
    return round(gross_bps - cout, 4)


def evaluer_recette(gross_bps: Any, cost_base_bps: Any, *, lcb_marge_bps: float = 0.0) -> dict[str, Any]:
    """Net par scénario + verdict de promotion : PROMOTE seulement si ADVERSE_P95 reste > marge."""
    if not isinstance(gross_bps, (int, float)) or not isinstance(cost_base_bps, (int, float)):
        return {"nets": {s: UNMEASURABLE for s in SCENARIOS}, "verdict": "MORE_DATA"}
    nets = {s: net_sous_scenario(gross_bps, cost_base_bps, s) for s in SCENARIOS}
    # promotion : doit survivre a ADVERSE_P95 (et donc a BASE). Optimistic ignore pour le verdict.
    promote = nets["ADVERSE_P95"] > lcb_marge_bps
    verdict = "PROMOTE" if promote else ("KILL" if nets["BASE_CALIBRATED"] <= 0 else "MORE_DATA")
    return {"nets": nets, "promote_si_adverse_p95": promote, "verdict": verdict,
            "note": "OPTIMISTIC = diagnostic seulement, ne promeut jamais"}


def verdict_bloque_si_optimiste(scenario_source: str, verdict: str) -> str:
    """Garde-fou : un verdict PROMOTE issu du scénario OPTIMISTIC est rétrogradé."""
    if verdict == "PROMOTE" and not peut_promote(scenario_source):
        return "MORE_DATA"
    return verdict


__all__ = ["SCENARIOS", "SCENARIOS_PROMOTE", "peut_promote", "net_sous_scenario",
           "evaluer_recette", "verdict_bloque_si_optimiste", "UNMEASURABLE"]
