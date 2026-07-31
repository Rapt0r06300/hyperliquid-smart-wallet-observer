"""ALPHA P12 — RECETTE économique : 4 scénarios de coût. OPTIMISTIC ne PROMOTE jamais.

Chaque idée est jugée sous plusieurs régimes de coût, pour ne garder que ce qui survit à l'adverse :
  * BASE_CALIBRATED         — coûts calibrés réalistes (référence de décision) ;
  * ADVERSE_P95 / ADVERSE_P99 — coûts stressés (slippage/latence au P95/P99) ;
  * OPTIMISTIC_DIAGNOSTIC_ONLY — borne haute, DIAGNOSTIC seulement, **ne peut jamais promouvoir**.

Un PROMOTE exige de survivre au moins jusqu'à ADVERSE_P95. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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


# ── FIX-58 : RECETTE FINALE — table économique complète par survivant + PROMOTE si TOUS les gates passent ──
#: colonnes de la table finale (task FIX-58). L'optimistic reste DIAGNOSTIC (jamais promote).
COLONNES_FINALES = ("idea", "N", "gross_bps", "fees_bps", "spread_bps", "slippage_bps", "latency_bps",
                    "net_base_bps", "lcb_net_bps", "pf", "dd", "es", "fill_ratio", "capacity_usd",
                    "oos_net_bps", "forward_net_bps", "net_adverse_p95_bps", "net_adverse_p99_bps",
                    "net_optimistic_diag_bps", "verdict")


def _cout_base_bps(profil: Mapping[str, Any]) -> Any:
    parts = [profil.get(k) for k in ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")]
    mesures = [float(x) for x in parts if isinstance(x, (int, float))]
    return sum(mesures) if mesures else UNMEASURABLE


def ligne_finale(profil: Mapping[str, Any]) -> dict[str, Any]:
    """Une ligne de la recette finale : nets par scénario + les 4 GATES. PROMOTE seulement si survit à
    ADVERSE_P95 ET LCB(net)>0 ET OOS>0 ET forward>0 (tout mesuré). L'optimistic ne promeut jamais."""
    gross, cout = profil.get("gross_bps"), _cout_base_bps(profil)
    rec = evaluer_recette(gross, cout)
    nets = rec["nets"]
    lcb, oos, fwd = profil.get("lcb_net_bps"), profil.get("oos_net_bps"), profil.get("forward_net_bps")
    gates = {
        "adverse_p95": bool(rec.get("promote_si_adverse_p95")),
        "lcb_net_positif": isinstance(lcb, (int, float)) and lcb > 0,
        "oos_positif": isinstance(oos, (int, float)) and oos > 0,
        "forward_positif": isinstance(fwd, (int, float)) and fwd > 0,
    }
    base = nets.get("BASE_CALIBRATED")
    if all(gates.values()):
        verdict = "PROMOTE"
    elif isinstance(base, (int, float)) and base <= 0:
        verdict = "KILL"
    else:
        verdict = "MORE_DATA"
    row = {c: profil.get(c) for c in COLONNES_FINALES}
    row.update({"idea": profil.get("idea") or profil.get("_famille"),
                "net_base_bps": base, "net_adverse_p95_bps": nets.get("ADVERSE_P95"),
                "net_adverse_p99_bps": nets.get("ADVERSE_P99"),
                "net_optimistic_diag_bps": nets.get("OPTIMISTIC_DIAGNOSTIC_ONLY"),
                "cout_base_bps": (round(cout, 4) if isinstance(cout, (int, float)) else cout),
                "gates": gates, "verdict": verdict})
    return row


def recette_finale(survivants: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Chaque survivant (issu de la Factory H24) passe BASE_CALIBRATED → ADVERSE_P95 → ADVERSE_P99. Table
    complète + comptes. Sans survivant → rien à promouvoir (honnête : la recette vient APRÈS les survivants)."""
    survivants = list(survivants or [])
    table = [ligne_finale(p) for p in survivants]
    n = {"PROMOTE": 0, "KILL": 0, "MORE_DATA": 0}
    for r in table:
        n[r["verdict"]] = n.get(r["verdict"], 0) + 1
    return {"colonnes": list(COLONNES_FINALES), "table": table, "n_survivants": len(table),
            "n_promote": n["PROMOTE"], "n_kill": n["KILL"], "n_more_data": n["MORE_DATA"],
            "note": "OPTIMISTIC = diagnostic seulement ; PROMOTE exige adverse_p95 + LCB + OOS + forward",
            "real_execution": False}


__all__ = ["SCENARIOS", "SCENARIOS_PROMOTE", "peut_promote", "net_sous_scenario",
           "evaluer_recette", "verdict_bloque_si_optimiste", "COLONNES_FINALES", "ligne_finale",
           "recette_finale", "UNMEASURABLE"]
