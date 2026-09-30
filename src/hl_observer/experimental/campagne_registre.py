"""CAMPAGNE ADOSSÉE AU REGISTRE (LOT14 P10, Flo 26/07). Chemin CANONIQUE que tout runner d'expériences
doit emprunter pour qu'AUCUNE variante n'échappe au registre, et pour que DSR/PBO soient alimentés par la
DISTRIBUTION DE TOUS LES ESSAIS (gagnants ET KILL), pas seulement les survivants.

Séquence obligatoire par variante :
  1. `preenregistrer(...)`  AVANT exécution — écrit un essai `phase=preregistration`, result=None (figé) ;
  2. exécuter la variante hors de ce module (backtest/markout) ;
  3. `enregistrer_resultat(...)` APRÈS — écrit un ÉVÉNEMENT SÉPARÉ `phase=resultat` (append-only, ne
     réécrit jamais la préregistration) portant le Sharpe et le verdict.
Puis `juger_famille(...)` déflate le Sharpe (DSR sur TOUS les Sharpe du registre) et calcule le PBO CSCV.
0 réseau, 0 ordre.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.experimental import registre_essais as REG
from hl_observer.research_parallel import validation as VAL


def preenregistrer(root: Path, *, family: str, variant: str, params: dict, data_cutoff=None, universe=None,
                   horizon=None, cost_model_version=None, execution_model_version=None) -> dict:
    """Étape 1 : essai PRÉ-ENREGISTRÉ (sans résultat). Immuable une fois écrit (append-only)."""
    return REG.enregistrer(root, {"family": family, "variant": variant, "params": params,
                                  "data_cutoff": data_cutoff, "universe": universe, "horizon": horizon,
                                  "cost_model_version": cost_model_version,
                                  "execution_model_version": execution_model_version,
                                  "result": None, "pass_kill": None, "phase": "preregistration"})


def enregistrer_resultat(root: Path, *, family: str, variant: str, params: dict, sharpe, result: str,
                         pass_kill: str, data_cutoff=None, universe=None, horizon=None,
                         cost_model_version=None, execution_model_version=None) -> dict:
    """Étape 3 : ÉVÉNEMENT SÉPARÉ append-only portant le résultat. Ne réécrit JAMAIS la préregistration —
    le registre garde donc préreg ET résultat (traçabilité complète, aucun renommage possible)."""
    return REG.enregistrer(root, {"family": family, "variant": variant, "params": params, "sharpe": sharpe,
                                  "data_cutoff": data_cutoff, "universe": universe, "horizon": horizon,
                                  "cost_model_version": cost_model_version,
                                  "execution_model_version": execution_model_version,
                                  "result": result, "pass_kill": pass_kill, "phase": "resultat"})


def juger_famille(root: Path, *, family: str, nets_gagnante: list[float], perf_par_variante: dict,
                  s: int = 8) -> dict:
    """DSR de la variante retenue (ses nets par épisode) DÉFLATÉ par les Sharpe de TOUS les essais-résultats
    du registre (KILL compris) ; PBO CSCV sur les MÊMES variantes (vrais blocs temporels via pbo_cscv).
    ARM seulement si DSR significatif ET PBO < 0,5. Retourne les compteurs pour l'audit."""
    essais = REG.charger(root)
    resultats = [e for e in essais if e.get("family") == family and e.get("phase") == "resultat"]
    sharpes = REG.sharpes_tous_essais(resultats, family=family)     # TOUS les résultats (gagnants + KILL)
    d = VAL.dsr(nets_gagnante, sharpes_essais=sharpes)
    p = VAL.pbo_cscv(perf_par_variante, s=s)
    pbo = p.get("pbo")
    significatif = bool(d.get("significatif")) and (pbo is not None and pbo < 0.5)
    return {"family": family, "n_preregistrations": sum(1 for e in essais
                                                        if e.get("family") == family and e.get("phase") == "preregistration"),
            "n_resultats": len(resultats), "n_sharpes_dsr": len(sharpes), "dsr": d, "pbo": pbo,
            "verdict": "ARM" if significatif else "SHADOW_OU_KILL"}


__all__ = ["preenregistrer", "enregistrer_resultat", "juger_famille"]
