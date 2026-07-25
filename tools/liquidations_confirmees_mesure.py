"""MESURE fade/continuation des liquidations CONFIRMÉES (fill.liquidation = REAL_LIQUIDATION) au bid/ask
RÉEL de la bbo_tape HL. RÉUTILISE l'existant : `liquidation_real_exec` (join bbo + exécution réelle ask/bid
+ résumé) et `rapid_alpha_run` (2 fenêtres, leave-one-out, drawdown). PUR, 0 réseau, 0 ordre.

Provenance : SEULEMENT les liquidations où liquidatedUser == vault suivi (le forced-flow du user, signal
tradeable), jamais un proxy. Dédup en épisodes (coin+hash : une liquidation = plusieurs fills au même hash).
Sens du fade : forced SELL (close long, signe<0) → on FADE en achetant (dir +1) ; forced BUY → dir −1.
Coûts RÉELS (spread bbo payé + 9 bps A/R + latence). Épisodes hors bbo_tape = NON_MESURABLE_NO_BBO (jamais inventé).
"""
from __future__ import annotations

import collections
import importlib.util
import json
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("liquidation_real_exec", RACINE / "tools" / "liquidation_real_exec.py")
LRE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LRE)
RAR = LRE.RAR

JOURNAL = RACINE / "runtime" / "data" / "liquidations_confirmees.jsonl"
SORTIE = RACINE / "runtime" / "rapports" / "liquidation_cascade"
HORIZONS_S = LRE.HORIZONS_S


def charger_episodes(path: Path = JOURNAL) -> tuple[list, dict]:
    """Confirmées → épisodes dédupliqués (coin+hash). Un épisode = {coin, t, sens, role}.

    SENS DU FORCED-FLOW DU LIQUIDÉ (ce qui dislocate le prix) : on utilise TOUS les fills liquidation!=null,
    en dérivant le côté forcé via liquidatedUser :
      • notre vault EST le liquidé (liquidatedUser==vault) → le forced-flow = SON signe ;
      • notre vault est le LIQUIDATEUR (liquidatedUser!=vault) → il prend l'AUTRE côté ⇒ forced = −signe.
    forced_signe<0 = liquidé force-VENDU (long liquidé) → prix poussé BAS → on FADE en achetant (SELL_OVERSHOOT)."""
    recs = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()] if path.exists() else []
    stats = {"n_fills": len(recs), "n_vault_liquide": 0, "n_liquidateur": 0}
    par = collections.OrderedDict()
    for r in recs:
        est_vault_liquide = str(r.get("liquidatedUser") or "").lower() == str(r.get("vault") or "").lower()
        stats["n_vault_liquide" if est_vault_liquide else "n_liquidateur"] += 1
        signe = r.get("signe") or 0
        if signe == 0:
            continue
        forced_signe = signe if est_vault_liquide else -signe
        cle = (r.get("coin"), r.get("hash"))
        if cle in par:
            continue
        par[cle] = {"coin": r.get("coin"), "t": int(r.get("ts_ms")),
                    "sens": "SELL_OVERSHOOT" if forced_signe < 0 else "BUY_OVERSHOOT",
                    "role": "liquide" if est_vault_liquide else "liquidateur"}
    stats["n_episodes"] = len(par)
    return list(par.values()), stats


def executer(path: Path = JOURNAL, *, horizon_ref: int = 30) -> dict:
    SORTIE.mkdir(parents=True, exist_ok=True)
    ev, stats = charger_episodes(path)
    serie = LRE.charger_hl_bbo({e["coin"] for e in ev})
    mes = [LRE.mesurer_reel_bbo(e, serie.get(e["coin"], ([], []))) for e in ev]
    ok = [m for m in mes if m["statut"] == "OK"]
    no_bbo = sum(1 for m in mes if m["statut"] == "NON_MESURABLE_NO_BBO")
    coins_couverts = sorted({m["coin"] for m in ok})
    rap = {"ts_ms": int(time.time() * 1000), "provenance": "REAL_LIQUIDATION (fill.liquidation)",
           "fills_confirmes": stats["n_fills"], "vault_liquide": stats["n_vault_liquide"],
           "liquidateur": stats["n_liquidateur"], "episodes_vault_liquide": stats["n_episodes"],
           "episodes_avec_bbo_reel": len(ok), "episodes_sans_bbo": no_bbo,
           "coins_couverts": coins_couverts,
           "par_horizon": {str(h): LRE._resume(ok, h) for h in HORIZONS_S},
           "deux_moities@ref": RAR.deux_fenetres_ep(ok, horizon_ref),
           "leave_one_out@ref": RAR.leave_one_out(ok, horizon_ref)}
    r = rap["par_horizon"][str(horizon_ref)]
    d2 = rap["deux_moities@ref"]
    loo = rap["leave_one_out@ref"]
    armable = bool(r.get("n") and r.get("net_moyen", -1) > 0 and d2.get("probe_armable")
                   and all(v is not None and v > 0 for v in loo.values()))
    if stats["n_episodes"] == 0:
        motif = "AUCUNE_DONNEE_CONFIRMEE"
    elif len(ok) == 0:
        motif = "CONFIRMEES_PRESENTES_MAIS_AUCUNE_COUVERTURE_BBO_L2"
    elif armable:
        motif = "ARME_EXPLORATOIRE_REAL"
    else:
        motif = "SHADOW_ONLY (couverture/2-moities/leave-one-out insuffisants)"
    rap["decision"] = motif
    (SORTIE / "liquidations_confirmees_mesure.json").write_text(
        json.dumps(rap, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return rap


if __name__ == "__main__":
    r = executer()
    print("CONFIRMEES: %d fills (vault_liquide=%d, liquidateur=%d) -> %d episodes" % (
        r["fills_confirmes"], r["vault_liquide"], r["liquidateur"], r["episodes_vault_liquide"]))
    print("COUVERTURE BBO/L2: %d episodes avec bid/ask reel, %d sans (coins couverts=%s)" % (
        r["episodes_avec_bbo_reel"], r["episodes_sans_bbo"], r["coins_couverts"]))
    for h in HORIZONS_S:
        print("  @%3ds:" % h, r["par_horizon"][str(h)])
    print("DECISION:", r["decision"])
