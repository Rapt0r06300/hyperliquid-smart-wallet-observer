"""ALPHA P33/P44/P45 — GATES de validation : cost-aware, early-stop séquentiel, multiple-testing.

- **P33 cost-aware gate** : ne trade que si `LCB(gross) > P95(coût total) + marge`. Pas moyenne > moyenne.
- **P44 early-stop** : KILL si LCB clairement < 0 avec N suffisant ; MORE_DATA si incertain ; jamais stopper
  favorablement après une série chanceuse.
- **P45 multiple-testing** : plus la recherche est massive, plus PROMOTE est dur. On exige que l'edge (LCB)
  dépasse l'espérance du MAX de N bruits gaussiens ≈ σ·√(2·ln N) (borne d'union classique).

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def cost_aware_gate(lcb_gross_bps: float | None, p95_cost_bps: float | None, *, marge_bps: float = 1.0) -> dict[str, Any]:
    """P33 — autorise le trade seulement si LCB(gross) > P95(coût) + marge. Sinon NO_TRADE."""
    if not isinstance(lcb_gross_bps, (int, float)) or not isinstance(p95_cost_bps, (int, float)):
        return {"trade": False, "raison": "UNMEASURABLE", "marge_effective_bps": UNMEASURABLE}
    marge = lcb_gross_bps - (p95_cost_bps + marge_bps)
    return {"trade": bool(marge > 0), "raison": ("OK" if marge > 0 else "LCB_GROSS<=P95_COUT+MARGE"),
            "marge_effective_bps": round(marge, 4)}


def early_stop(lcb_net_bps: float | None, n_independent: int, *, n_min: int = 8,
               seuil_kill_bps: float = 0.0) -> str:
    """P44 — KILL si LCB net clairement <=0 avec assez de votes ; MORE_DATA si incertain ; sinon CONTINUE."""
    if not isinstance(lcb_net_bps, (int, float)) or n_independent < n_min:
        return "MORE_DATA"
    if lcb_net_bps <= seuil_kill_bps:
        return "KILL"
    return "CONTINUE"


def attendu_max_bruit_bps(n_trials: int, sigma_bps: float) -> float:
    """P45 — espérance du MAX de N bruits gaussiens N(0,σ) ≈ σ·√(2·ln N). Seuil que l'edge doit dépasser."""
    n = max(2, int(n_trials))
    return round(float(sigma_bps) * math.sqrt(2.0 * math.log(n)), 4)


def passe_multiple_testing(edge_lcb_bps: float | None, sigma_bps: float | None, n_trials: int) -> dict[str, Any]:
    """P45 — l'edge (LCB) survit-il à la correction multiple-testing pour N essais réels ?"""
    if not isinstance(edge_lcb_bps, (int, float)) or not isinstance(sigma_bps, (int, float)) or sigma_bps <= 0:
        return {"passe": False, "raison": "UNMEASURABLE", "seuil_bps": UNMEASURABLE}
    seuil = attendu_max_bruit_bps(n_trials, sigma_bps)
    return {"passe": bool(edge_lcb_bps > seuil), "seuil_bps": seuil,
            "raison": ("OK" if edge_lcb_bps > seuil else "EDGE<=E[max de N bruits]")}


def verdict_final(*, lcb_net_bps: float | None, n_independent: int, sigma_bps: float | None, n_trials: int,
                  cost_incomplet: bool) -> str:
    """Combine les gates : coût complet requis, early-stop, puis multiple-testing. Défaut prudent."""
    if cost_incomplet:
        return "MORE_DATA"                              # coût partiel -> jamais CANDIDAT
    es = early_stop(lcb_net_bps, n_independent)
    if es != "CONTINUE":
        return es
    mt = passe_multiple_testing(lcb_net_bps, sigma_bps, n_trials)
    return "CANDIDAT" if mt["passe"] else "MORE_DATA"


__all__ = ["cost_aware_gate", "early_stop", "attendu_max_bruit_bps", "passe_multiple_testing",
           "verdict_final", "UNMEASURABLE"]
