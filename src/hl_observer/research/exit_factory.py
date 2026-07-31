"""ALPHA P35 — EXIT FACTORY : sorties pré-enregistrées, GELÉES avant OOS, comparées sur NET/DD/temps.

Familles d'exit : horizon fixe, convergence (retour au fair), signal opposé, détérioration microstructure,
time stop, stop loss, take profit. La règle d'exit est choisie sur la DÉCOUVERTE et GELÉE ; l'OOS ne fait
que MESURER la règle gelée (jamais de re-sélection sur l'OOS). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# HORIZON_FIXE/SL/TP/TIME_STOP/SIGNAL_OPPOSE + CONVERGENCE (retour au fair) + DETERIORATION_MICRO (santé micro).
EXITS = ("HORIZON_FIXE", "STOP_LOSS", "TAKE_PROFIT", "TIME_STOP", "SIGNAL_OPPOSE",
         "CONVERGENCE", "DETERIORATION_MICRO")


def _sortie(m: float, dd: float, t: int, cause: str) -> dict[str, Any]:
    return {"net_bps": round(m, 4), "dd_bps": round(dd, 4), "sortie_pas": t, "cause": cause}


def simuler_exit(chemin_bps: Sequence[float], *, regle: str, sl_bps: float = 30.0, tp_bps: float = 40.0,
                 horizon: int = 5, time_stop: int = 20, signal_oppose_a: int | None = None,
                 conv_frac: float = 0.5, sante_micro: Sequence[float] | None = None,
                 micro_seuil: float = 0.0) -> dict[str, Any]:
    """Applique une règle d'exit sur un chemin de markout SIGNÉ (bps depuis l'entrée). Retourne net + DD.

    CONVERGENCE : sort quand le markout, après un pic favorable, revient à `conv_frac` du pic (retour au fair).
    DETERIORATION_MICRO : sort quand la santé microstructure passe sous `micro_seuil`. SANS série `sante_micro`
    la micro-détérioration est UNMEASURABLE (net=None, cause MICRO_NA) — jamais un 0 fabriqué."""
    if not chemin_bps:
        return {"net_bps": None, "dd_bps": None, "sortie_pas": None}
    if regle == "DETERIORATION_MICRO" and sante_micro is None:
        return {"net_bps": None, "dd_bps": None, "sortie_pas": None, "cause": "MICRO_NA"}
    dd = 0.0
    peak = 0.0
    for t, m in enumerate(chemin_bps):
        dd = min(dd, m)
        peak = max(peak, m)
        if regle == "STOP_LOSS" and m <= -sl_bps:
            return _sortie(m, dd, t, "SL")
        if regle == "TAKE_PROFIT" and m >= tp_bps:
            return _sortie(m, dd, t, "TP")
        if regle == "HORIZON_FIXE" and t >= horizon:
            return _sortie(m, dd, t, "H")
        if regle == "TIME_STOP" and t >= time_stop:
            return _sortie(m, dd, t, "TIME")
        if regle == "SIGNAL_OPPOSE" and signal_oppose_a is not None and t >= signal_oppose_a:
            return _sortie(m, dd, t, "OPP")
        if regle == "CONVERGENCE" and peak > 0 and m <= conv_frac * peak:
            return _sortie(m, dd, t, "CONV")
        if regle == "DETERIORATION_MICRO" and sante_micro is not None \
                and t < len(sante_micro) and sante_micro[t] <= micro_seuil:
            return _sortie(m, dd, t, "MICRO")
    m = chemin_bps[-1]
    return {"net_bps": round(m, 4), "dd_bps": round(min(dd, m), 4), "sortie_pas": len(chemin_bps) - 1, "cause": "FIN"}


def comparer_exits(chemins: Sequence[Sequence[float]], *, regles: Sequence[str] = EXITS,
                   **params: Any) -> dict[str, Any]:
    """Net moyen + DD moyen par règle (sur un ensemble de chemins). La meilleure règle se GÈLE avant OOS.
    NB : `params` est PARTAGÉ pour tous les chemins ; DETERIORATION_MICRO n'est donc mesurable ici qu'avec
    une `sante_micro` commune (sinon net=None → n=0). Pour une santé micro par chemin, utiliser `simuler_exit`."""
    res = {}
    for r in regles:
        outs = [simuler_exit(c, regle=r, **params) for c in chemins if c]
        nets = [o["net_bps"] for o in outs if o["net_bps"] is not None]
        dds = [o["dd_bps"] for o in outs if o["dd_bps"] is not None]
        res[r] = {"net_moyen_bps": round(sum(nets) / len(nets), 4) if nets else None,
                  "dd_moyen_bps": round(sum(dds) / len(dds), 4) if dds else None, "n": len(nets)}
    return res


def choisir_regle_gelee(chemins_decouverte: Sequence[Sequence[float]], *, regles: Sequence[str] = EXITS,
                        **params: Any) -> dict[str, Any]:
    """DÉCOUVERTE → choisit la règle au meilleur net moyen (égalité : DD le moins négatif) et la GÈLE.
    Aucune règle mesurable (toutes n=0) → `regle`=None (rien à geler)."""
    table = comparer_exits(chemins_decouverte, regles=regles, **params)
    candidats = [(r, s) for r, s in table.items() if s["n"] > 0 and s["net_moyen_bps"] is not None]
    if not candidats:
        return {"regle": None, "table": table}
    best = max(candidats, key=lambda rs: (rs[1]["net_moyen_bps"],
              rs[1]["dd_moyen_bps"] if rs[1]["dd_moyen_bps"] is not None else -1e9))
    return {"regle": best[0], "table": table}


def mesurer_regle_gelee(chemins_oos: Sequence[Sequence[float]], regle: str | None,
                        **params: Any) -> dict[str, Any]:
    """OOS → MESURE UNIQUEMENT la règle déjà gelée (aucune re-sélection sur l'OOS)."""
    if regle is None:
        return {"regle": None, "net_moyen_bps": None, "dd_moyen_bps": None, "n": 0}
    s = comparer_exits(chemins_oos, regles=(regle,), **params)[regle]
    return {"regle": regle, **s}


def factory_exit(chemins_decouverte: Sequence[Sequence[float]], chemins_oos: Sequence[Sequence[float]], *,
                 regles: Sequence[str] = EXITS, **params: Any) -> dict[str, Any]:
    """Pipeline discipliné : choisit+GÈLE la règle d'exit sur la découverte, puis la MESURE sur l'OOS.
    L'OOS ne re-choisit jamais — il ne fait que révéler ce que la règle gelée aurait rapporté."""
    choix = choisir_regle_gelee(chemins_decouverte, regles=regles, **params)
    oos = mesurer_regle_gelee(chemins_oos, choix["regle"], **params)
    return {"regle_gelee": choix["regle"], "decouverte": choix["table"], "oos": oos}


__all__ = ["EXITS", "simuler_exit", "comparer_exits", "choisir_regle_gelee", "mesurer_regle_gelee",
           "factory_exit"]
