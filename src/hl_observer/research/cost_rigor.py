"""[AUD-238/239] Rigueur des couts : STRESS de couts NON heuristique (recalcul du net sous des
multiplicateurs croissants -> pire cas) et calibration POINT-IN-TIME des couts (le cout EN VIGUEUR
a l'instant du trade, jamais un cout FUTUR -> anti-fuite). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Sequence, Tuple


def stress_couts(pnls_bruts: Sequence[float], couts_par_trade: Sequence[float], *,
                 multiplicateurs: Sequence[float] = (1.0, 1.5, 2.0, 3.0)) -> dict:
    """STRESS de couts NON heuristique : recalcule le PnL NET sous chaque multiplicateur de cout et
    rend le PIRE cas. Un edge qui ne survit qu'a des couts optimistes n'est pas un edge."""
    n = min(len(pnls_bruts), len(couts_par_trade))
    resultats = {}
    for m in multiplicateurs:
        net = sum(pnls_bruts[i] - couts_par_trade[i] * m for i in range(n))
        resultats[m] = {"net_total": net, "survit": net > 0}
    pire = min(multiplicateurs, key=lambda m: resultats[m]["net_total"])
    return {"resultats": resultats, "pire_multiplicateur": pire,
            "net_pire_cas": resultats[pire]["net_total"],
            "robuste_aux_couts": all(r["survit"] for r in resultats.values())}


def cout_point_in_time(historique_couts: Sequence[Tuple[float, float]], ts_trade: float) -> dict:
    """Calibration POINT-IN-TIME : rend le cout EN VIGUEUR a `ts_trade` = le dernier cout connu dont
    l'horodatage d'effet est <= ts_trade. JAMAIS un cout futur (sinon fuite d'information look-ahead)."""
    candidats = [(t, c) for (t, c) in historique_couts if t <= ts_trade]
    if not candidats:
        return {"cout": None, "asof": None}
    t, c = max(candidats, key=lambda x: x[0])
    return {"cout": c, "asof": t}
