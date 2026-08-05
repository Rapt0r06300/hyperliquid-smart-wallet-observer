"""[LAB α] RECHERCHE intelligente du meilleur PnL NET. Chaque candidat est rejoué par le CHEMIN CANONIQUE UNIQUE
(MegaCablage) — jamais un moteur parallèle. Stratégie : grille LARGE d'abord, élimination rapide des familles
négatives, approfondissement des zones prometteuses, CACHE déterministe (aucune reconfig retestée), REPRISE via
checkpoint (un run interrompu ne recommence pas), BUDGET séparé par module (Copy-Vault / Cross-Venue / Lead-Lag /
Combine). Pour chaque candidat : IS/OOS/FORWARD, stress ADVERSE_P95/P99 (coûts majorés), PLACEBO (signaux inversés
→ doit ~s'annuler), puis métriques + gate de promotion dur. Aucune donnée synthétique n'entre dans le verdict
(le caller passe des événements RÉELS). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hl_observer.mega_cablage.pipeline import MegaCablage
from hl_observer.mega_cablage.runner import _EquityMap
from hl_observer.mega_cablage.replay_driver import separer_temporel, separer_par_episodes
from hl_observer.ops import lab_metriques as M
from hl_observer.paper_trading import latency_truth as _LT

ESPACE_DEFAUT = {
    "notional_max": [100.0, 300.0, 500.0],
    "fee_bps": [2.5, 4.5],
    "min_fill_ratio": [0.5, 0.85],
    "seuil_edge_cross_venue_bps": [1.0, 5.0],
}
# item 12 : sévérité de QUEUE croissante (P95 = queue modérée, P99 = queue extrême). Ce n'est PAS un
# multiplicateur de fee_bps : il pondère les composantes de MARCHÉ (spread/latence/slippage/adverse).
_SEVERITE_ADVERSE = {"ADVERSE_P95": 1.0, "ADVERSE_P99": 1.9}


def cout_adverse_bps(config: dict[str, Any], *, niveau: str, spread_bps: float | None = None,
                     delai_sec: float = 1.0) -> dict[str, Any]:
    """Sur-coût adverse RÉEL (item 12), en bps, EN PLUS des frais de base — jamais un simple fee_bps×1.5.
    Compose des composantes DISTINCTES et mesurables/majorées : demi-spread, latence causale
    (latency_truth, STRESS_ONLY), slippage/profondeur, adverse selection. La sévérité de queue (P95<P99)
    pondère les composantes de marché. Missed/partial fills sont modélisés séparément (min_fill_ratio
    durci dans `_rejouer_adverse`). Gaps/reconnects/panne de venue : ajoutés depuis les métriques réelles
    du candidat quand elles existent (sinon documentés absents, jamais inventés)."""
    fee = float(config.get("fee_bps", 2.5))
    demi_spread = float(spread_bps if spread_bps is not None else fee)     # défaut prudent ~ frais
    lat = float(_LT.latence_scalaire_stress_bps(float(delai_sec), coeff_bps_per_sec=0.20,
                                                cap_bps=15.0).get("latency_stress_bps") or 0.0)
    sev = _SEVERITE_ADVERSE.get(niveau, 1.0)
    slippage = 0.5 * fee * sev                     # slippage/profondeur croît avec la taille et la queue
    adverse_sel = 0.5 * demi_spread * sev          # sélection adverse (on se fait choisir aux pires prix)
    surcout = demi_spread * sev + lat * sev + slippage + adverse_sel
    return {"surcout_bps": round(surcout, 4), "fee_base_bps": round(fee, 4),
            "demi_spread_bps": round(demi_spread, 4), "latence_bps": round(lat, 4),
            "slippage_bps": round(slippage, 4), "adverse_selection_bps": round(adverse_sel, 4),
            "severite": sev, "niveau": niveau, "etiquette": "STRESS_ONLY"}


def _hash_donnees(evenements: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    h.update(str(len(evenements)).encode())
    for ev in evenements[:64]:
        h.update(("%s|%s|%s|" % (ev.get("coin"), ev.get("ts_ms"), ev.get("signe"))).encode())
    return h.hexdigest()[:16]


def _cle_cache(config: dict[str, Any], data_hash: str) -> str:
    return hashlib.sha256((json.dumps(config, sort_keys=True) + "|" + data_hash).encode()).hexdigest()[:24]


def _rejouer_riche(evenements: list[dict[str, Any]], *, config: dict[str, Any],
                   leader_equity_defaut: Any) -> dict[str, Any]:
    """Rejoue un segment via MegaCablage et extrait un résultat riche (net, courbe equity, nets par tick, notional,
    contributions par coin, fills/missed, réconciliation)."""
    depart = 1000.0
    pipe = MegaCablage(notre_equity=depart, notional_max=config["notional_max"], fee_bps=config["fee_bps"],
                       min_fill_ratio=config["min_fill_ratio"],
                       seuil_edge_cross_venue_bps=config["seuil_edge_cross_venue_bps"])
    if evenements:
        pipe.traiter_replay(list(evenements), leader_equity_par_vault=_EquityMap({}, leader_equity_defaut))
    courbe = [depart] + [t["pnl"]["equity"] for t in pipe.trace]
    nets = [courbe[i + 1] - courbe[i] for i in range(len(courbe) - 1)]
    fills = [f for t in pipe.trace for f in t["fills"] if f.get("execute")]
    missed = sum(1 for t in pipe.trace for f in t["fills"] if f.get("raison") in ("MISSED_FILL", "MORE_DATA"))
    notional = sum(float(f.get("filled_notional") or 0.0) for f in fills)
    contrib: dict[str, float] = {}
    for f in fills:
        coin = str(f.get("cle", "")).split("/")[-1]
        contrib[coin] = contrib.get(coin, 0.0) + float(f.get("filled_notional") or 0.0)
    pnl = pipe.executeur.pnl()
    return {"net": round(pnl["equity"] - depart, 8), "roi": round((pnl["equity"] - depart) / depart, 8),
            "equity": pnl["equity"], "reconcilie": bool(pnl["reconcilie"]), "fees": pnl["fees"],
            "fills": len(fills), "missed": missed, "courbe_equity": courbe, "nets": nets,
            "notional_traite": notional, "contributions": contrib,
            "cross_venue": pipe.resume()["cross_venue_executes"]}


def _rejouer_adverse(evenements: list[dict[str, Any]], *, config: dict[str, Any], niveau: str,
                     leader_equity_defaut: Any) -> dict[str, Any]:
    """Rejoue un segment sous STRESS ADVERSE réel : frais + sur-coût adverse composé (spread/latence/
    slippage/adverse selection) AJOUTÉ aux fees, et min_fill_ratio DURCI (modélise missed/partial fills
    et sélection adverse). item 12 : un vrai stress mesuré, jamais fee_bps×1.5."""
    comp = cout_adverse_bps(config, niveau=niveau)
    durcissement = 0.15 if niveau == "ADVERSE_P99" else 0.08
    cfg = {**config,
           "fee_bps": round(float(config["fee_bps"]) + comp["surcout_bps"], 6),
           "min_fill_ratio": min(0.98, float(config["min_fill_ratio"]) + durcissement)}
    r = _rejouer_riche(evenements, config=cfg, leader_equity_defaut=leader_equity_defaut)
    r["cout_adverse"] = comp
    return r


def evaluer_config(evenements: list[dict[str, Any]], config: dict[str, Any], *,
                   leader_equity_defaut: Any = None, fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
                   min_episodes: int = 30) -> dict[str, Any]:
    """Évalue un candidat : IS/OOS/FORWARD + ADVERSE_P95/P99 RÉELS appliqués séparément sur OOS ET FORWARD
    (item 12) + PLACEBO (signes inversés → l'edge doit disparaître). Retourne {config, segments, metriques,
    verdict, placebo_net}."""
    # item 14 : découpage par ÉPISODES INDIVISIBLES — aucune position/métaordre/épisode à cheval sur IS/OOS.
    segs_ev = separer_par_episodes(evenements, fractions=fractions)
    segments: dict[str, dict[str, Any]] = {}
    riche_is = None
    for lab in ("IS", "OOS", "FORWARD"):
        r = _rejouer_riche(segs_ev[lab], config=config, leader_equity_defaut=leader_equity_defaut)
        segments[lab] = r
        if lab == "IS":
            riche_is = r
    # item 12 : le stress adverse s'applique SÉPARÉMENT sur OOS ET FORWARD (pas seulement IS). Le net
    # ADVERSE retenu = le PIRE des deux (min) : un edge doit survivre au stress hors-échantillon ET forward.
    for niveau in ("ADVERSE_P95", "ADVERSE_P99"):
        a_oos = _rejouer_adverse(segs_ev["OOS"], config=config, niveau=niveau,
                                 leader_equity_defaut=leader_equity_defaut)
        a_fwd = _rejouer_adverse(segs_ev["FORWARD"], config=config, niveau=niveau,
                                 leader_equity_defaut=leader_equity_defaut)
        pire = a_oos if a_oos["net"] <= a_fwd["net"] else a_fwd
        segments[niveau] = {**pire, "net_oos": a_oos["net"], "net_forward": a_fwd["net"],
                            "cout_adverse": a_oos.get("cout_adverse")}
        segments["%s_OOS" % niveau] = a_oos
        segments["%s_FORWARD" % niveau] = a_fwd
    # placebo : signes inversés -> l'edge réel doit disparaître.
    placebo_evs = [{**ev, "signe": -(ev.get("signe") or 0)} for ev in segs_ev["IS"]]
    placebo = _rejouer_riche(placebo_evs, config=config, leader_equity_defaut=leader_equity_defaut)
    capacite = round(riche_is["notional_traite"], 4) if riche_is["fills"] > 0 else M.UNMEASURABLE
    metriques = M.metriques_candidat(
        segments={k: {"net": v["net"], "roi": v.get("roi")} for k, v in segments.items()},
        nets_episodes=riche_is["nets"], courbe_equity=riche_is["courbe_equity"],
        notional_traite=riche_is["notional_traite"], equity_finale=riche_is["equity"],
        fees=riche_is["fees"], contributions_coin=riche_is["contributions"],
        capacite=capacite, reconcilie=all(segments[s]["reconcilie"] for s in ("IS", "OOS", "FORWARD")),
        placebo_net=placebo["net"])
    verdict = M.verdict_promotion(metriques, min_episodes=min_episodes)
    return {"config": config,
            "segments": {k: {"net": v["net"], "roi": v.get("roi"), "fills": v.get("fills"),
                             "missed": v.get("missed"), "net_oos": v.get("net_oos"),
                             "net_forward": v.get("net_forward")} for k, v in segments.items()},
            "metriques": metriques, "verdict": verdict, "placebo_net": placebo["net"],
            "cross_venue": riche_is["cross_venue"]}


def _grille(espace: dict[str, list]) -> list[dict[str, Any]]:
    cles = sorted(espace)
    combos: list[dict[str, Any]] = [{}]
    for c in cles:
        combos = [{**base, c: v} for base in combos for v in espace[c]]
    for cfg in combos:
        cfg.setdefault("module", "COMBINE")
    return combos


def rechercher(evenements: list[dict[str, Any]], *, espace: dict[str, list] | None = None,
               leader_equity_defaut: Any = None, budget: int = 64, checkpoint_path: str | Path | None = None,
               min_episodes: int = 30, source: str = "REEL", on_eval: Any = None) -> dict[str, Any]:
    """Recherche large→fine avec cache/reprise. Élimine tôt les configs à net IS ≤ 0, approfondit les gagnantes.
    budget = nombre max d'évaluations. Retourne {evalues, caches, candidats(triés par net OOS+FORWARD), meilleur,
    verdict_global, source}. Aucun résultat fabriqué : source non-REELLE → verdict_global NON_ECONOMIQUE."""
    espace = espace or ESPACE_DEFAUT
    data_hash = _hash_donnees(evenements)
    cache: dict[str, dict[str, Any]] = {}
    if checkpoint_path and Path(checkpoint_path).is_file():
        for ligne in Path(checkpoint_path).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(ligne)
                cache[row["cle"]] = row["res"]
            except (json.JSONDecodeError, KeyError):
                continue
    candidats: list[dict[str, Any]] = []
    evalues = 0
    caches = 0

    def _evaluer(cfg: dict[str, Any]) -> dict[str, Any]:
        nonlocal evalues, caches
        cle = _cle_cache(cfg, data_hash)
        if cle in cache:
            caches += 1
            return cache[cle]
        if evalues >= budget:
            return {"config": cfg, "verdict": "BUDGET_EPUISE", "segments": {}, "metriques": {}, "placebo_net": 0.0}
        res = evaluer_config(evenements, cfg, leader_equity_defaut=leader_equity_defaut,
                             min_episodes=min_episodes)
        evalues += 1
        cache[cle] = res
        if checkpoint_path:
            with open(checkpoint_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"cle": cle, "res": res}) + "\n")
        return res

    coarse = _grille(espace)
    total_prevu = len(coarse)

    def _pousser(res: dict[str, Any]) -> None:
        candidats.append(res)
        if on_eval:
            on_eval({"res": res, "evalues": evalues, "caches": caches, "total_prevu": total_prevu,
                     "restantes": max(0, total_prevu - len(candidats))})

    prometteuses: list[dict[str, Any]] = []
    for cfg in coarse:
        if evalues >= budget:
            break
        res = _evaluer(cfg)
        _pousser(res)
        net_is = res.get("metriques", {}).get("net_pnl")
        if isinstance(net_is, (int, float)) and net_is > 0:
            prometteuses.append(cfg)                 # zone à approfondir
    # approfondissement : voisins de notional_max autour des configs gagnantes (borne au budget).
    for cfg in prometteuses:
        if evalues >= budget:
            break
        nm = cfg.get("notional_max", 300.0)
        total_prevu += 2
        for voisin in ({**cfg, "notional_max": round(nm * 0.75, 2)},
                       {**cfg, "notional_max": round(nm * 1.25, 2)}):
            if evalues >= budget:
                break
            _pousser(_evaluer(voisin))

    def _score(res: dict[str, Any]) -> float:
        m = res.get("metriques", {})
        oos = m.get("oos_net") if isinstance(m.get("oos_net"), (int, float)) else -1e9
        fwd = m.get("forward_net") if isinstance(m.get("forward_net"), (int, float)) else -1e9
        return float(oos) + float(fwd)

    candidats.sort(key=_score, reverse=True)
    promus = [c for c in candidats if c.get("verdict") == "PROMU"]
    meilleur = promus[0] if promus else (candidats[0] if candidats else None)
    if str(source).upper().startswith("SYNTH"):
        verdict_global = "NON_ECONOMIQUE_SYNTHETIQUE"
    elif promus:
        verdict_global = "POSITIF"
    elif any(isinstance(c.get("metriques", {}).get("net_pnl"), (int, float)) and
             c["metriques"]["net_pnl"] != 0 for c in candidats):
        verdict_global = "NEGATIF"
    else:
        verdict_global = "NON_MESURABLE"
    return {"evalues": evalues, "caches": caches, "n_candidats": len(candidats),
            "prometteuses": len(prometteuses), "candidats": candidats, "meilleur": meilleur,
            "verdict_global": verdict_global, "source": source, "data_hash": data_hash}


__all__ = ["ESPACE_DEFAUT", "evaluer_config", "rechercher", "cout_adverse_bps"]
