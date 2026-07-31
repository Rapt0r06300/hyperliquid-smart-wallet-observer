"""ALPHA P35 — EXIT FACTORY : sorties pré-enregistrées, GELÉES avant OOS, comparées sur NET/DD/temps.

Familles d'exit : horizon fixe, convergence (retour au fair), signal opposé, détérioration microstructure,
time stop, stop loss, take profit. La règle d'exit est choisie sur la découverte et GELÉE ; l'OOS ne fait
que mesurer. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

EXITS = ("HORIZON_FIXE", "STOP_LOSS", "TAKE_PROFIT", "TIME_STOP", "SIGNAL_OPPOSE")


def simuler_exit(chemin_bps: Sequence[float], *, regle: str, sl_bps: float = 30.0, tp_bps: float = 40.0,
                 horizon: int = 5, time_stop: int = 20, signal_oppose_a: int | None = None) -> dict[str, Any]:
    """Applique une règle d'exit sur un chemin de markout signé (bps depuis l'entrée). Retourne net + DD."""
    if not chemin_bps:
        return {"net_bps": None, "dd_bps": None, "sortie_pas": None}
    dd = 0.0
    for t, m in enumerate(chemin_bps):
        dd = min(dd, m)
        if regle == "STOP_LOSS" and m <= -sl_bps:
            return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": "SL"}
        if regle == "TAKE_PROFIT" and m >= tp_bps:
            return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": "TP"}
        if regle == "HORIZON_FIXE" and t >= horizon:
            return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": "H"}
        if regle == "TIME_STOP" and t >= time_stop:
            return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": "TIME"}
        if regle == "SIGNAL_OPPOSE" and signal_oppose_a is not None and t >= signal_oppose_a:
            return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": "OPP"}
    m = chemin_bps[-1]
    return {"net_bps": round(m, 4), "dd_bps": round(min(dd, m), 4), "sortie_pas": len(chemin_bps) - 1, "cause": "FIN"}


def comparer_exits(chemins: Sequence[Sequence[float]], *, regles: Sequence[str] = EXITS,
                   **params: Any) -> dict[str, Any]:
    """Net moyen + DD moyen par règle (sur un ensemble de chemins). La meilleure règle se GÈLE avant OOS."""
    res = {}
    for r in regles:
        outs = [simuler_exit(c, regle=r, **params) for c in chemins if c]
        nets = [o["net_bps"] for o in outs if o["net_bps"] is not None]
        dds = [o["dd_bps"] for o in outs if o["dd_bps"] is not None]
        res[r] = {"net_moyen_bps": round(sum(nets) / len(nets), 4) if nets else None,
                  "dd_moyen_bps": round(sum(dds) / len(dds), 4) if dds else None, "n": len(nets)}
    return res


__all__ = ["EXITS", "simuler_exit", "comparer_exits"]
