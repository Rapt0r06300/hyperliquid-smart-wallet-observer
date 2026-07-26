"""PIPELINE 18 h RÉEL (LOT18H-WIRING, Flo 26/07) — le travail effectif de chaque phase, branché dans la
boucle. Rien ici n'est une façade : chaque fonction produit des trials, des résultats, une validation, un
holdout et un forward paper à partir d'un CORPUS d'épisodes (fixtures en test, archives réelles en prod).

MOTEUR EXACT ÉVÉNEMENTIEL (distinct de mesurer_phase 14 h) : entrée au prix EXÉCUTABLE (croise le spread),
sortie au mid forward de l'HORIZON demandé (donc 250 ms ≠ 1 s), coûts A/R complets (frais entrée+sortie,
demi-spread de sortie, slippage, impact, latence feed+decision+entry+response), remplissage maker par file
(partiel / no-fill) + adverse selection. FAST_SCREEN reste approximatif et ne peut jamais atteindre le holdout.

Objectif directeur : chercher LARGE (familles × directions × horizons × régimes × coins × params) puis ne
GARDER que ce qui survit aux coûts et au holdout. 0 réseau, 0 ordre, PAPER-ONLY.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import registre_18h as REG          # noqa: E402
import validation_18h as V18        # noqa: E402
from hl_observer.research_parallel import validation as VAL  # noqa: E402

HORIZONS_MS = (100, 250, 500, 1000, 2000, 3000, 5000, 10000, 15000, 30000, 60000,
               120000, 300000, 900000, 1800000, 3600000)
COUT_APPROX_AR_BPS = 12.0
#: bornes pour l'embargo réel = max(horizon, latence max, durée max des features) — jamais 1 ms codé en dur.
LATENCE_MAX_MS = 2000.0
FEATURE_DUREE_MAX_MS = 60000.0


# ─────────────── moteur EXACT événementiel ───────────────
def moteur_exact(ep: dict, *, sens: int, horizon_ms: int, modele_exec: str = "taker",
                 notional_usd: float = 100.0) -> dict | None:
    """Net RÉEL (bps) d'UN épisode via le moteur d'exécution PROD-TRUTH (prix exécutables ask→bid/bid→ask,
    PnL depuis entry_px/exit_px, coûts séparés). None si le carnet d'entrée est invalide (contrat historique).
    Conserve les clés legacy (net_bps, statut, fill, entree_prix, brut_bps, cout_bps) + l'objet épisode complet."""
    import moteur_execution_prod as MEP
    o = MEP.evaluer_episode(ep, sens=sens, horizon_ms=horizon_ms, modele_exec=modele_exec, notional_usd=notional_usd)
    st = o.get("status")
    if st == "NO_DATA":
        return None                                        # carnet invalide -> None (contrat historique)
    if st == "UNMEASURABLE":
        return {"net_bps": None, "statut": "UNMEASURABLE", "horizon_ms": horizon_ms}
    if st == "NO_FILL":
        return {"net_bps": None, "statut": "NO_FILL", "horizon_ms": horizon_ms, "fill": 0.0}
    cout = round(o.get("fees_bps", 0.0) + o.get("slippage_bps", 0.0) + o.get("impact_bps", 0.0)
                 + o.get("latency_bps", 0.0) + o.get("funding_bps", 0.0), 4)
    return {"net_bps": o["net_bps"], "brut_bps": o.get("gross_bps"), "cout_bps": cout,
            "fill": o.get("fill"), "horizon_ms": horizon_ms, "sens": sens, "modele": modele_exec,
            "entree_prix": o.get("entry_px"), "sortie_prix": o.get("exit_px"),
            "maker": modele_exec != "taker", "statut": "OK", "episode": o}


def nets_exact(corpus: list[dict], *, sens: int, horizon_ms: int, modele_exec: str = "taker") -> list[dict]:
    """Renvoie UN OBJET PAR ÉPISODE (episode_id, entry_ts, exit_ts, status, net_bps, …), de MÊME longueur que
    `corpus`. On ne filtre JAMAIS pour re-zipper : UNMEASURABLE/NO_FILL/NO_DATA gardent leur identité.
    Pour la liste des net mesurés, utiliser `_nets_ok(...)`."""
    import moteur_execution_prod as MEP
    return MEP.evaluer_episodes(corpus, sens=sens, horizon_ms=horizon_ms, modele_exec=modele_exec)


def _nets_ok(episodes: list[dict]) -> list[float]:
    """Flux MESURÉ (diagnostic) : net_bps des épisodes status OK (APPROXIMATE inclus, pour AFFICHAGE seulement).
    Un UNMEASURABLE/NO_FILL ne devient jamais 0. NE PAS utiliser pour promouvoir."""
    return [o["net_bps"] for o in episodes if o.get("status") == "OK" and o.get("net_bps") is not None]


def _nets_promo(episodes: list[dict]) -> list[float]:
    """Flux PROMOUVABLE (P0) : ne garde que ce qui peut réellement devenir survivant/candidat/pépite/PASS :
    status == OK AND promotable == True AND exit_source == FWD_BOOK. Une sortie APPROXIMATE (fwd_mid±spread)
    est diagnostique mais JAMAIS promouvable."""
    return [o["net_bps"] for o in episodes
            if o.get("status") == "OK" and o.get("promotable") is True
            and o.get("exit_source") == "FWD_BOOK" and o.get("net_bps") is not None]


# ─────────────── FAST_SCREEN (approx, ne promeut jamais) ───────────────
def fast_screen_variante(corpus: list[dict], *, sens: int, horizon_ms: int,
                         cout_ar_bps: float = COUT_APPROX_AR_BPS) -> dict:
    """Approx : net = médiane(brut top-of-book) − coût forfaitaire conservateur. Marqué NON éligible."""
    bruts = []
    for ep in corpus:
        mid = (float(ep["bid"]) + float(ep["ask"])) / 2.0
        fwd = (ep.get("fwd_mid") or {}).get(horizon_ms) or (ep.get("fwd_mid") or {}).get(str(horizon_ms))
        if fwd is None or mid <= 0:
            continue
        bruts.append(sens * (float(fwd) - mid) / mid * 1e4)
    net = (statistics.median(bruts) - cout_ar_bps) if bruts else None
    return {"moteur": "FAST_SCREEN", "n": len(bruts), "net_approx_bps": net,
            "garder": bool(net is not None and len(bruts) >= 5 and net > -cout_ar_bps),
            "drapeaux": ["APPROXIMATE_ONLY", "NOT_VALIDATED", "NOT_ELIGIBLE_FOR_FORWARD"], "peut_promouvoir": False}


# ─────────────── génération de variantes ───────────────
def generer_variantes(*, familles, directions, horizons, regimes, coins, params_grille) -> list[dict]:
    """Produit family × direction × horizon × régime × coin × params. Chaque variante est un trial candidat."""
    out = []
    for fam in familles:
        for d in directions:
            for h in horizons:
                for reg in regimes:
                    for coin in coins:
                        for pv in params_grille:
                            out.append({"family": fam, "direction": int(d), "horizon_ms": int(h),
                                        "regime": reg, "coin": coin, "params": dict(pv)})
    return out


def embargo_reel(horizons, *, latence_max_ms: float = LATENCE_MAX_MS, feature_dur_max_ms: float = FEATURE_DUREE_MAX_MS) -> float:
    """Embargo/purge = max(horizon max du trial, latence maximale, durée maximale des features). Jamais 1 ms."""
    return max([float(h) for h in horizons] + [float(latence_max_ms), float(feature_dur_max_ms)])


def _filtrer_corpus(corpus, *, coin=None, regime=None, predicat=None, family=None, seuil=None):
    """Filtre par coin/régime ET, si `predicat` fourni, par le prédicat RÉEL de la famille sur l'épisode.
    Une famille dont la donnée ne porte pas le prédicat renvoie 0 épisode -> DATA_MISSING honnête (jamais
    un net générique mal étiqueté)."""
    out = []
    for e in corpus:
        if coin is not None and e.get("coin") != coin:
            continue
        if regime is not None and e.get("regime") != regime:
            continue
        if predicat is not None and not predicat(e, family, seuil):
            continue
        out.append(e)
    return out


# ─────────────── PHASE DISCOVERY ───────────────
def phase_discovery(rundir: Path, corpus_disc: list[dict], variantes: list[dict], *, code_sha: str,
                    source_hash: str, top_survivants: int = 8, stop_event=None, predicat=None) -> dict:
    """Préenregistre CHAQUE variante, FAST_SCREEN sur discovery, enregistre TOUS les résultats (KILL compris),
    EXACT_REPLAY sur les survivants (successive halving), sans masquer aucune variante testée. INTERRUPTIBLE :
    vérifie stop_event à chaque variante (Ctrl+C traité en secondes, FINAL-9)."""
    rundir = Path(rundir)
    n_prereg = n_fast = n_exact = 0
    survivants = []
    for v in variantes:
        if stop_event is not None and stop_event.is_set():   # interruption rapide en plein replay
            break
        ph = REG.parameter_hash({**v["params"], "dir": v["direction"], "h": v["horizon_ms"],
                                 "reg": v["regime"], "coin": v["coin"], "code": code_sha, "src": source_hash,
                                 "part": "discovery"})
        tid = REG.trial_id(v["family"], "%s_%dms_%s" % (v["coin"], v["horizon_ms"], v["regime"]), ph)
        REG.preenregistrer(rundir, {"trial_id": tid, "family": v["family"],
                                    "variant": "%s_%s_%dms" % (v["coin"], "L" if v["direction"] > 0 else "S", v["horizon_ms"]),
                                    "parameter_hash": ph, "source_hash": source_hash, "data_partition": "discovery",
                                    "horizons": [v["horizon_ms"]], "coins": [v["coin"]], "regime": v["regime"],
                                    "direction": v["direction"], "cost_model": "AR_complet", "latency_model": "feed+dec+entry+resp",
                                    "fill_model": "taker", "code_sha": code_sha, "params": v["params"]})
        n_prereg += 1
        sub = _filtrer_corpus(corpus_disc, coin=v["coin"], regime=v["regime"], predicat=predicat,
                              family=v["family"], seuil=(v.get("params") or {}).get("seuil"))
        fs = fast_screen_variante(sub, sens=v["direction"], horizon_ms=v["horizon_ms"])
        n_fast += 1
        if not fs["garder"]:
            REG.enregistrer_resultat(rundir, tid, {"family": v["family"], "variant": tid, "phase": "discovery",
                                                   "moteur": "FAST_SCREEN", "net_median_bps": fs["net_approx_bps"],
                                                   "sharpe": None, "pf": None, "verdict": "KILL_FAST"})
            continue
        # EXACT_REPLAY sur le survivant : SEULS les nets PROMOUVABLES (FWD_BOOK) décident du survivant (P0)
        nets = _nets_promo(nets_exact(sub, sens=v["direction"], horizon_ms=v["horizon_ms"]))
        n_exact += 1
        net_med = statistics.median(nets) if nets else None
        sh = VAL.sharpe(nets) if len(nets) >= 2 else None
        pf = _profit_factor(nets)
        verdict = "SURVIVANT_DISCOVERY" if (net_med is not None and net_med > 0) else "KILL"
        REG.enregistrer_resultat(rundir, tid, {"family": v["family"], "variant": tid, "phase": "discovery",
                                               "moteur": "EXACT_REPLAY", "n": len(nets), "net_median_bps": net_med,
                                               "sharpe": sh, "pf": pf, "verdict": verdict,
                                               "horizon_ms": v["horizon_ms"], "coin": v["coin"], "regime": v["regime"],
                                               "direction": v["direction"]})
        if verdict == "SURVIVANT_DISCOVERY":
            survivants.append({"trial_id": tid, **v, "net_median_bps": net_med, "sharpe": sh, "pf": pf, "nets": nets})
    survivants.sort(key=lambda s: -(s["net_median_bps"] or -1e9))
    survivants = survivants[:top_survivants]                # successive halving : on ne garde que le haut du panier
    (rundir / "resultats").mkdir(parents=True, exist_ok=True)
    (rundir / "resultats" / "discovery_survivants.json").write_text(
        json.dumps([{k: s[k] for k in ("trial_id", "family", "coin", "horizon_ms", "regime", "direction",
                                        "net_median_bps", "sharpe", "pf")} for s in survivants],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return {"n_preregistres": n_prereg, "n_fast_screen": n_fast, "n_exact_replays": n_exact,
            "n_survivants": len(survivants), "survivants": survivants}


def _profit_factor(nets):
    gains = sum(x for x in nets if x > 0)
    pertes = -sum(x for x in nets if x < 0)
    return round(gains / pertes, 4) if pertes > 0 else (None if not gains else float("inf"))


# ─────────────── PHASE DEDUP_FREEZE ───────────────
def phase_freeze(rundir: Path, survivants: list[dict], *, code_sha: str) -> dict:
    """Déduplique les variantes fonctionnellement identiques (family+coin+direction+horizon), vérifie une
    stabilité de paramètres minimale, fige candidats/coûts/modèles/horizons/critères -> CANDIDATES_FROZEN.json."""
    rundir = Path(rundir)
    vus, uniques = set(), []
    for s in survivants:
        cle = (s["family"], s["coin"], s["direction"], s["horizon_ms"])
        if cle in vus:
            continue
        vus.add(cle)
        uniques.append(s)
    frozen = {"code_sha": code_sha, "gele": True, "criteres": V18.SEUILS,
              "candidats": [{**{k: s[k] for k in ("trial_id", "family", "coin", "horizon_ms", "regime", "direction",
                                                  "net_median_bps", "sharpe", "pf")},
                             "params": s.get("params") or {}} for s in uniques]}
    (rundir / "resultats" / "CANDIDATES_FROZEN.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"n_candidats_figes": len(uniques), "gele": True}


def candidats_geles(rundir: Path) -> list[dict]:
    try:
        return json.loads((Path(rundir) / "resultats" / "CANDIDATES_FROZEN.json").read_text(encoding="utf-8")).get("candidats", [])
    except (OSError, ValueError):
        return []


# ─────────────── PHASE VALIDATION ───────────────
def phase_validation(rundir: Path, corpus_val: list[dict], *, survivants: list[dict], stop_event=None) -> dict:
    """Sur archive VALIDATION uniquement : exact replay, walk-forward, placebos RÉELLEMENT rejoués (direction
    opposée recalculée depuis les prix, pas −net), DSR/PBO réels depuis le registre. INTERRUPTIBLE (PT-8) :
    vérifie stop_event à chaque candidat."""
    rundir = Path(rundir)
    (rundir / "resultats").mkdir(parents=True, exist_ok=True)
    sharpes_tous = REG.sharpes_tous_resultats(rundir)       # TOUS les essais terminaux (multiplicité)
    perf_pbo, rapports = {}, []
    interrompu = False
    for s in survivants:
        if stop_event is not None and stop_event.is_set():   # arrêt coopératif en pleine validation
            interrompu = True
            break
        sub = _filtrer_corpus(corpus_val, coin=s["coin"], regime=s["regime"])
        episodes = nets_exact(sub, sens=s["direction"], horizon_ms=s["horizon_ms"])
        nets = _nets_promo(episodes)                          # P0 : seuls les PROMOUVABLES (FWD_BOOK) valident
        # walk-forward par ÉPISODE PROMOUVABLE (ts propre, jamais un zip filtrer→réassocier)
        eps = [{"ts_ms": o["entry_ts"], "net_bps": o["net_bps"]} for o in episodes
               if o.get("status") == "OK" and o.get("promotable") and o.get("exit_source") == "FWD_BOOK"]
        emb_s = embargo_reel([s["horizon_ms"]])               # FX-9 : embargo RÉEL = max(horizon,latence,features), jamais 1 ms
        wf = V18.walk_forward(eps, k=3, embargo_ms=emb_s)
        # PLACEBO direction opposée RÉELLEMENT rejoué (recalcul par prix)
        nets_opp = _nets_promo(nets_exact(sub, sens=-s["direction"], horizon_ms=s["horizon_ms"]))
        # PLACEBO coin aléatoire compatible (autre coin, même régime)
        autres = [c for c in {e["coin"] for e in corpus_val} if c != s["coin"]]
        nets_coin = _nets_promo(nets_exact(_filtrer_corpus(corpus_val, coin=(autres[0] if autres else s["coin"]), regime=s["regime"]),
                                           sens=s["direction"], horizon_ms=s["horizon_ms"]))
        boot = V18.bootstrap_bloc(nets)
        d = VAL.dsr(nets, sharpes_essais=sharpes_tous) if len(nets) >= 8 else {"dsr": None}
        perf_pbo[s["trial_id"]] = nets
        rap = {"trial_id": s["trial_id"], "family": s["family"], "coin": s["coin"], "horizon_ms": s["horizon_ms"],
               "n": len(nets), "net_median_bps": (statistics.median(nets) if nets else None),
               "net_moyen_bps": (statistics.fmean(nets) if nets else None), "pf": _profit_factor(nets),
               "wf_oos_net_median_bps": wf.get("oos_net_median_bps"),
               "placebo_opposee_median_bps": (statistics.median(nets_opp) if nets_opp else None),
               "placebo_coin_median_bps": (statistics.median(nets_coin) if nets_coin else None),
               "ic_bas_bps": boot.get("ic_bas"), "ic_haut_bps": boot.get("ic_haut"), "dsr": d.get("dsr")}
        rapports.append(rap)
    pbo = VAL.pbo_cscv(perf_pbo, s=4) if len(perf_pbo) >= 2 else {"pbo": None}
    (rundir / "resultats" / "validation.json").write_text(
        json.dumps({"rapports": rapports, "pbo": pbo.get("pbo"), "n_sharpes_dsr": len(sharpes_tous)},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return {"n_valides": len(rapports), "pbo": pbo.get("pbo"), "rapports": rapports, "interrompu": interrompu}


# ─────────────── PHASE HOLDOUT + FORWARD PAPER ───────────────
def phase_holdout_forward(rundir: Path, corpus_hold: list[dict], corpus_fwd: list[dict], *,
                          validation: list[dict], freeze_ts: float = 0.0, embargo_ms: float = 1.0,
                          data_cutoff=None, portefeuille_global_dir=None) -> dict:
    """HOLDOUT ≠ FORWARD (P2). Le holdout (avant freeze_ts) sert AUX MÉTRIQUES OOS. Le forward paper ne rejoue
    QUE des événements STRICTEMENT après le gel (exchange_ts > freeze_ts) — jamais le holdout réutilisé. Aucun
    tuning. Chaque candidat conserve freeze_ts / data_cutoff / last_forward_event_id / n_live / régimes / etc."""
    rundir = Path(rundir)
    geles = candidats_geles(rundir)
    if not geles:
        return {"holdout": "AUCUN_CANDIDAT_GELE", "freeze_ts": freeze_ts}
    # garde-fou DUR : le forward ne contient que du STRICTEMENT après le gel (disjoint du holdout)
    corpus_fwd = [e for e in corpus_fwd if e.get("ts_ms", 0) > freeze_ts]
    lignes_fwd, hold = [], []
    for c in geles:
        sub_h = _filtrer_corpus(corpus_hold, coin=c["coin"], regime=c["regime"])
        nets_h = _nets_promo(nets_exact(sub_h, sens=c["direction"], horizon_ms=c["horizon_ms"]))   # P0
        # PRÉ-FORWARD (archive, STRICTEMENT après le gel) — PAS le « forward live » (celui-ci = registre_candidats_live,
        # alimenté par le CanonicalStore). Filtré par COIN seul (le régime dérive ; on ENREGISTRE les régimes vus).
        sub_f = _filtrer_corpus(corpus_fwd, coin=c["coin"])
        n_live = 0
        last_fwd_id = None
        regimes_vus = set()
        for ep in sub_f:
            r = moteur_exact(ep, sens=c["direction"], horizon_ms=c["horizon_ms"])
            evt = {"trial_id": c["trial_id"], "coin": c["coin"], "ts_ms": ep.get("ts_ms"),
                   "type": ("FILL" if r and r.get("statut") == "OK" else (r or {}).get("statut", "NO_DATA")),
                   "net_bps": (r or {}).get("net_bps")}
            lignes_fwd.append(evt)
            n_live += 1
            last_fwd_id = ep.get("episode_id") or ep.get("ts_ms")
            regimes_vus.add(ep.get("regime"))
        vr = next((v for v in validation if v["trial_id"] == c["trial_id"]), {})
        nm_h = statistics.median(nets_h) if nets_h else None
        pf_h = _profit_factor(nets_h) if nets_h else None
        dd_h = V18.max_drawdown_bps(nets_h) if nets_h else None
        # stress RÉEL : on ampute chaque net d'un surcoût conservateur et on regarde si la médiane survit
        stress_extra = V18.SEUILS.get("stress_extra_bps", 3.0)
        stress_survit = (statistics.median([x - stress_extra for x in nets_h]) > 0) if nets_h else None
        # AF-P0 : plateau de PARAMÈTRES (prédicat famille), stabilité horizons SÉPARÉE, concentration = MÊME
        # signal filtré, capacité exigeant du L2 réel — tous sur le flux PROMOUVABLE uniquement.
        import metriques_pepites as MP
        import moteur_execution_prod as MEP
        import familles_continue as FAM
        fam = c["family"]
        seuil0 = (c.get("params") or {}).get("seuil")
        a_pred = FAM.FEATURE_REQUISE.get(fam) is not None
        # évaluateur générique (par horizon) pour la stabilité d'horizons
        ev_nets = lambda corp, s, h: _nets_promo(nets_exact(corp, sens=s, horizon_ms=h))
        # évaluateur au seuil courant (prédicat famille) pour le plateau de paramètres
        def _ev_seuil(seuil):
            sub = _filtrer_corpus(sub_h, predicat=FAM.predicat, family=fam, seuil=seuil)
            return _nets_promo(nets_exact(sub, sens=c["direction"], horizon_ms=c["horizon_ms"]))
        # évaluateur par coin (MÊME signal filtré) pour la concentration
        def _ev_coin(coin):
            sub = _filtrer_corpus(corpus_hold, coin=coin, regime=c["regime"], predicat=FAM.predicat, family=fam, seuil=seuil0)
            return _nets_promo(nets_exact(sub, sens=c["direction"], horizon_ms=c["horizon_ms"]))
        plat = MP.plateau_parametres(seuil=seuil0, evaluer_seuil=_ev_seuil, famille_a_predicat=a_pred)
        stab_h = MP.stabilite_horizons(sub_h, sens=c["direction"], horizon_ms=c["horizon_ms"], evaluer_nets=ev_nets)
        coins_dispo = sorted({e["coin"] for e in corpus_hold})
        conc = MP.concentration_reelle(coins=coins_dispo, evaluer_coin=_ev_coin)
        capa = MP.capacite_reelle(sub_h, sens=c["direction"], horizon_ms=c["horizon_ms"], courbe_capacite=MEP.courbe_capacite)
        hold.append({"trial_id": c["trial_id"], "family": fam, "coin": c["coin"], "horizon_ms": c["horizon_ms"],
                     "freeze_ts": freeze_ts, "data_cutoff": data_cutoff, "embargo_ms": embargo_ms,
                     "n_pre_forward": n_live, "n_forward_live": n_live, "pre_forward": True,
                     "last_forward_event_id": last_fwd_id,
                     "forward_regimes": sorted(str(r) for r in regimes_vus if r is not None),
                     "n_holdout": len(nets_h), "holdout_net_median_bps": nm_h,
                     "holdout_pf": pf_h, "holdout_drawdown_bps": dd_h, "stress_survit": stress_survit,
                     "plateau": plat.get("plateau_parametres"), "plateau_motif": plat.get("motif"),
                     "stabilite_horizons": stab_h.get("stabilite_horizons"),
                     "un_seul_coin_dominant": conc.get("un_seul_coin_dominant"),
                     "capacite_non_nulle": capa.get("capacite_non_nulle"), "capacite_motif": capa.get("motif"),
                     "capacite_courbe": capa.get("courbe"), "concentration": conc.get("contribution"),
                     "validation_net_median_bps": vr.get("net_median_bps"), "dsr": vr.get("dsr"),
                     "pbo": None,  # rempli par reconcilier (pbo global de la campagne)
                     "ic_bas_bps": vr.get("ic_bas_bps"), "placebo_opposee_median_bps": vr.get("placebo_opposee_median_bps")})
    (rundir / "resultats" / "holdout.json").write_text(json.dumps(hold, ensure_ascii=False, indent=1), encoding="utf-8")
    with (rundir / "ledger" / "forward_paper.jsonl").open("w", encoding="utf-8") as f:
        for e in lignes_fwd:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    # GR-2 : ce PRÉ-FORWARD (archive, post-gel) est DIAGNOSTIC UNIQUEMENT. Il tourne sur un portefeuille paper
    # LOCAL et n'alimente JAMAIS le portefeuille GLOBAL du run (ni son PnL/ROI/DD). Le portefeuille GLOBAL n'est
    # alimenté que par le VRAI live (épisodes CanonicalStore FWD_BOOK reçus après freeze_exchange_ts), câblé dans
    # recherche_continue._suivi_candidats_live. `portefeuille_global_dir` est donc ignoré ici (volontairement).
    reco_pf = None
    try:
        import forward_portefeuille as FPF
        import moteur_execution_prod as MEP
        from portefeuille_paper import PortefeuillePaper
        pf_local = PortefeuillePaper(1000.0, levier=3.0)      # LOCAL : diagnostic pré-forward, jamais le global
        pending_path = rundir / "ledger" / "pending_exits.json"
        sim = FPF.simuler(geles, corpus_fwd, filtrer=_filtrer_corpus,
                          evaluer=lambda ep, sens, horizon_ms: MEP.evaluer_episode(ep, sens=sens, horizon_ms=horizon_ms),
                          portefeuille=pf_local, pending_path=pending_path)
        if hasattr(sim["portefeuille"], "ecrire_ledger"):    # ledger de campagne (diagnostic), séparé du global
            sim["portefeuille"].ecrire_ledger(rundir / "ledger" / "forward_portfolio.jsonl")
        reco_pf = sim["reconciliation"]
        (rundir / "resultats" / "forward_portfolio_reconciliation.json").write_text(
            json.dumps({**reco_pf, "n_signaux": sim["n_signaux"], "n_ouverts": sim["n_ouverts"],
                        "n_refuses": sim["n_refuses"], "pre_forward_diagnostic": True,
                        "alimente_global": False}, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — le portefeuille ne doit pas casser le pipeline, mais l'erreur est visible
        (rundir / "resultats" / "forward_portfolio_reconciliation.json").write_text(
            json.dumps({"erreur": str(e)[:200]}, ensure_ascii=False), encoding="utf-8")
    return {"n_holdout": len(hold), "n_forward_events": len(lignes_fwd), "holdout": hold,
            "forward_portfolio_reconciliation": reco_pf, "pre_forward_diagnostic": True}


# ─────────────── réconciliation + verdicts finaux ───────────────
def reconcilier_et_juger(rundir: Path, *, holdout: list[dict], pbo, notional_usd: float = 100.0,
                         securise=None) -> dict:
    """PnL/ROI depuis les nets, verdict final via le gate scellé (holdout vu). ROI capital total ET immobilisé.
    Métriques RÉELLES : plateau/concentration/capacité viennent du holdout ; ledger_reconcilie du portefeuille
    forward ; securite_verte de l'audit (passé une fois par le run)."""
    rundir = Path(rundir)
    finals = []
    # ledger réconcilié = cohérence RÉELLE du portefeuille forward de la campagne
    ledger_ok = None
    try:
        ledger_ok = bool(json.loads((rundir / "resultats" / "forward_portfolio_reconciliation.json").read_text(encoding="utf-8")).get("coherent"))
    except (OSError, ValueError):
        ledger_ok = None
    if not isinstance(holdout, list):                 # aucun candidat gelé -> pas de verdict final (honnête)
        holdout = []
    seuils = V18.SEUILS
    for h in holdout:
        if not isinstance(h, dict):
            continue
        nm = h.get("holdout_net_median_bps")
        ic = h.get("ic_bas_bps")
        dd = h.get("holdout_drawdown_bps")
        # métriques RÉELLEMENT calculées ; celles non calculées dans ce chemin restent None -> DATA_MISSING (PT-4).
        cand = {"n": h.get("n_holdout", 0), "net_median_oos_bps": nm, "net_moyen_oos_bps": nm,
                "pf_oos": h.get("holdout_pf"),                      # vrai profit factor du holdout
                "dsr": h.get("dsr"), "pbo": pbo,
                "ic_bas_bps": ic, "placebo_median_bps": h.get("placebo_opposee_median_bps"),
                "stress_survit": h.get("stress_survit"),           # vrai stress (net amputé)
                "plateau": h.get("plateau"),                        # UF-3 : rejoué sur horizons voisins
                "un_seul_coin_dominant": h.get("un_seul_coin_dominant"),   # UF-3 : contribution multi-coins
                "drawdown_borne": (None if dd is None else bool(dd <= seuils["drawdown_max_bps"])),
                "capacite_non_nulle": h.get("capacite_non_nulle"), # UF-3 : profondeur/VWAP/fills, pas l'IC
                "ledger_reconcilie": ledger_ok,                     # cohérence RÉELLE du portefeuille forward
                "securite_verte": securise,                         # audit sécurité (passé une fois par le run)
                "holdout_vu": True}
        g = V18.gate(cand)
        verdict = g["verdict"]
        raisons = list(g["raisons"])
        if verdict == "PASS_FORWARD_PAPER":               # POINT 2 : ce chemin ne voit QUE le holdout + pré-forward
            verdict = "PASS_PRE_FORWARD"                   # ARCHIVE (diagnostic) -> jamais PASS_FORWARD_PAPER en direct ;
            raisons.append("PRE_FORWARD_ONLY_REQUIERT_PREUVE_LIVE")   # promu SEULEMENT si prouvé en LIVE (registre + global)
        pnl_usd = (nm or 0.0) / 1e4 * notional_usd
        finals.append({**h, "verdict": verdict, "raisons": raisons,
                       "pnl_usd_par_trade": round(pnl_usd, 4),   # ESPÉRANCE par trade (≠ PnL AGRÉGÉ, cf. réconciliation PT-10)
                       "roi_immobilise_pct": round((nm or 0.0) / 100.0, 4)})   # net bps -> % sur capital immobilisé
    (Path(rundir) / "resultats" / "final_verdicts.json").write_text(
        json.dumps(finals, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"finals": finals, "n_pass": sum(1 for f in finals if f["verdict"] == "PASS_FORWARD_PAPER"),
            "n_pass_pre_forward": sum(1 for f in finals if f["verdict"] == "PASS_PRE_FORWARD")}


# ─────────────── corpus (fixtures déterministes ; en prod : construit depuis les archives) ───────────────
def corpus_fixtures(*, n_par_coin: int = 60, coins=("BTC", "ETH"), regimes=("calme", "vol"),
                    seed: int = 7) -> list[dict]:
    """Corpus d'épisodes déterministe pour prouver le pipeline. Les prix forward DIFFÈRENT par horizon
    (250 ms ≠ 1 s) : un vrai mouvement court terme s'estompe ensuite. Un signal a un edge brut RÉEL à court
    horizon sur le régime 'vol' (pour qu'au moins une variante survive après coûts), négatif ailleurs."""
    import random
    rng = random.Random(seed)
    eps = []
    horodatage = 0
    # INTERLEAVE régimes/coins dans le TEMPS : chaque partition (discovery/validation/holdout) contient un
    # mélange des deux régimes et des deux coins (sinon la partition par ts skew le corpus).
    for i in range(n_par_coin):
        for coin in coins:
            for reg in regimes:
                horodatage += 1000
                mid = 100.0 + rng.uniform(-1, 1)
                spread = mid * (0.0004 if reg == "calme" else 0.0009)
                bid, ask = mid - spread / 2, mid + spread / 2
                # edge brut court terme (bps) : positif et net-positif seulement en régime 'vol' à court horizon
                edge_court = (rng.gauss(30, 8) if reg == "vol" else rng.gauss(-12, 6))
                fwd, fwd_b, fwd_a = {}, {}, {}
                for h in HORIZONS_MS:
                    decay = max(0.0, 1.0 - (h / 2000.0))      # l'edge s'estompe : ~0 au-delà de 2 s
                    e_bps = edge_court * decay + rng.gauss(0, 3)
                    m = mid * (1.0 + e_bps / 1e4)
                    fwd[h] = m
                    fwd_b[h] = m - spread / 2                 # vrai bid/ask FUTUR (FWD_BOOK -> promouvable)
                    fwd_a[h] = m + spread / 2
                # profondeur L2 réelle (pour la capacité) : quelques niveaux de part et d'autre
                asks = [[ask + k * spread, 3000.0] for k in range(5)]
                bids = [[bid - k * spread, 3000.0] for k in range(5)]
                eps.append({"coin": coin, "regime": reg, "ts_ms": float(horodatage),
                            "bid": bid, "ask": ask, "bid_sz": 5000.0, "ask_sz": 5000.0,
                            "queue_devant_sz": 200.0, "vol_traversant_sz": 800.0,
                            "fees_bps": 1.5, "slippage_bps": 0.8, "impact_bps": 0.2, "latence_bps": 0.3,
                            "fwd_mid": fwd, "fwd_bid": fwd_b, "fwd_ask": fwd_a, "bids": bids, "asks": asks})
    return eps


def corpus_depuis_archives(root: Path, *, max_episodes: int = 4000, horizons=HORIZONS_MS) -> tuple[list[dict], str]:
    """Construit des épisodes RÉELS depuis la tape BBO (bbo_tape.jsonl) : pour chaque tick, prix forward =
    mid d'un tick ULTÉRIEUR ~horizon plus tard (causal). Régime = spread (calme/vol). Rend (corpus, source).
    Repli sur fixtures marquées SYNTHETIC si données insuffisantes (jamais silencieux)."""
    import json as _j
    p = root / "runtime" / "data" / "bbo_tape.jsonl"
    par_coin: dict[str, list[dict]] = {}
    if p.exists():
        for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_episodes * 4:]:
            try:
                d = _j.loads(l)
            except ValueError:
                continue
            if d.get("venue") != "HL" or not (d.get("bid") and d.get("ask")):
                continue
            c = str(d.get("coin") or "").upper()
            ts = d.get("ts_wall_ms") or d.get("recu_ns")
            if not c or ts is None:
                continue
            par_coin.setdefault(c, []).append({"ts": float(ts) / (1e6 if ts > 1e14 else 1.0),
                                               "bid": float(d["bid"]), "ask": float(d["ask"])})
    eps = []
    for c, ticks in par_coin.items():
        ticks.sort(key=lambda x: x["ts"])
        mids = [(t["ts"], (t["bid"] + t["ask"]) / 2.0, t["bid"], t["ask"]) for t in ticks]
        for i, (ts, mid, bid, ask) in enumerate(mids):
            fwd = {}
            for h in horizons:
                j = i
                while j < len(mids) and mids[j][0] - ts < h:
                    j += 1
                if j < len(mids):
                    fwd[h] = mids[j][1]
            if not fwd:
                continue
            spread = (ask - bid) / mid if mid else 0
            eps.append({"coin": c, "regime": ("vol" if spread > 0.0006 else "calme"), "ts_ms": ts,
                        "bid": bid, "ask": ask, "bid_sz": 3000.0, "ask_sz": 3000.0,
                        "queue_devant_sz": 200.0, "vol_traversant_sz": 600.0,
                        "fees_bps": 1.5, "slippage_bps": 0.8, "impact_bps": 0.2, "latence_bps": 0.3, "fwd_mid": fwd})
            if len(eps) >= max_episodes:
                break
    if len(eps) >= 100:
        return eps, "archives:bbo_tape"
    return corpus_fixtures(), "SYNTHETIC_FALLBACK"       # honnête : marqué synthétique si trop peu de données


def executer_pipeline_complet(root: Path, rundir: Path, corpus: list[dict], *, code_sha: str,
                              source_hash: str = "fixtures", horizons=(250, 1000, 5000, 30000),
                              variantes=None, stop_event=None, predicat=None, securise=None,
                              portefeuille_global_dir=None) -> dict:
    """Chaîne les 7 phases sur un corpus (fixtures en test, archives en prod), en SÉPARANT les partitions
    temporelles (anti-fuite) : discovery/validation/holdout par ts. Retourne les compteurs prouvant que la
    boucle produit RÉELLEMENT trials/replays/validation/holdout/forward. Écrit tous les artefacts."""
    rundir = Path(rundir)
    for sd in ("resultats", "ledger", "results", "partitions", "manifeste"):
        (rundir / sd).mkdir(parents=True, exist_ok=True)
    # EMBARGO RÉEL (P2) = max(horizon du trial, latence max, durée max des features) — jamais 1 ms codé en dur.
    embargo_ms = embargo_reel(horizons)
    # plafond de FAISABILITÉ : l'embargo ne peut pas manger plus de ~8% de la fenêtre (sinon les partitions
    # s'effondrent) — sur des données réelles (heures), 60 s << 8% et le plafond ne s'active jamais.
    tss = [e["ts_ms"] for e in corpus]
    span = (max(tss) - min(tss)) if tss else 0.0
    embargo_eff = min(embargo_ms, span * 0.08) if span > 0 else embargo_ms
    split = V18.partitions_par_quantiles(tss, horizon_max_ms=embargo_eff)
    V18.sceller_split(rundir, split)
    disc = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "discovery"]
    val = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "validation"]
    hold_full = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "holdout"]
    if not hold_full and corpus:                             # repli robuste : partition holdout vide (embargo/quantiles)
        ts_all = sorted(e["ts_ms"] for e in corpus)
        s55 = ts_all[int(len(ts_all) * 0.55)]
        s75 = ts_all[int(len(ts_all) * 0.75)]
        disc = disc or [e for e in corpus if e["ts_ms"] < s55]
        val = val or [e for e in corpus if s55 <= e["ts_ms"] < s75]
        hold_full = [e for e in corpus if e["ts_ms"] >= s75]
    # HOLDOUT ≠ FORWARD (P2) : le gel se produit au MILIEU du holdout. holdout = avant le gel (métriques OOS) ;
    # forward = STRICTEMENT après le gel (exchange_ts > freeze_ts). Les deux ensembles sont DISJOINTS par ts.
    ts_hold = sorted(e["ts_ms"] for e in hold_full)
    freeze_ts = (ts_hold[len(ts_hold) // 3] if ts_hold else 0.0)   # gel au 1er tiers -> forward = 2/3 restants
    hold = [e for e in hold_full if e["ts_ms"] <= freeze_ts]
    forward = [e for e in hold_full if e["ts_ms"] > freeze_ts]
    (rundir / "resultats" / "freeze.json").write_text(json.dumps(
        {"freeze_ts": freeze_ts, "embargo_ms": embargo_ms, "embargo_effectif_ms": embargo_eff,
         "n_holdout": len(hold), "n_forward": len(forward),
         "data_cutoff": (max(e["ts_ms"] for e in disc) if disc else None)}, ensure_ascii=False, indent=1), encoding="utf-8")
    coins = sorted({e["coin"] for e in corpus})
    regimes = sorted({e["regime"] for e in corpus})
    if variantes is None:
        variantes = generer_variantes(familles=("OFI", "SWEEP"), directions=(1, -1), horizons=horizons,
                                      regimes=regimes, coins=coins, params_grille=({"seuil": 8},))
    # normalise les variantes du scheduler (coins:[c]) vers le champ singulier attendu ; remappe les coins
    # ABSENTS du corpus vers un coin réellement présent (round-robin) pour ne pas gaspiller le budget en
    # trials vides — la nouveauté reste portée par family/horizon/direction/seuil.
    vnorm = []
    for i, v in enumerate(variantes):
        c = v.get("coin") or (v.get("coins") or [None])[0]
        if coins and c not in coins:
            c = coins[i % len(coins)]
        reg = v.get("regime")
        if regimes and reg not in regimes:                 # régime inconnu du corpus -> "tous régimes" (pas de filtre)
            reg = None
        vnorm.append({**v, "coin": c, "regime": reg, "params": v.get("params") or {"seuil": 8}})
    d = phase_discovery(rundir, disc or corpus, vnorm, code_sha=code_sha, source_hash=source_hash,
                        stop_event=stop_event, predicat=predicat)
    fr = phase_freeze(rundir, d["survivants"], code_sha=code_sha)
    v = phase_validation(rundir, val or corpus, survivants=d["survivants"], stop_event=stop_event)
    # arrêt coopératif (PT-8) : si stop demandé, on ne lance PAS le holdout/forward (partiel honnête)
    if stop_event is not None and stop_event.is_set():
        resume = {"n_variantes": len(vnorm), **{k: d[k] for k in ("n_preregistres", "n_fast_screen", "n_exact_replays", "n_survivants")},
                  "n_candidats_figes": fr["n_candidats_figes"], "n_valides": v["n_valides"], "pbo": v.get("pbo"),
                  "n_holdout": 0, "n_forward_events": 0, "n_pass": 0, "interrompu": True}
        (rundir / "resultats" / "pipeline_resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
        return resume
    hf = phase_holdout_forward(rundir, hold or corpus, forward, validation=v["rapports"],
                               freeze_ts=freeze_ts, embargo_ms=embargo_ms,
                               data_cutoff=(max(e["ts_ms"] for e in disc) if disc else None),
                               portefeuille_global_dir=portefeuille_global_dir)
    rec = reconcilier_et_juger(rundir, holdout=hf.get("holdout", []), pbo=v.get("pbo"), securise=securise)
    resume = {"n_variantes": len(variantes), **{k: d[k] for k in ("n_preregistres", "n_fast_screen", "n_exact_replays", "n_survivants")},
              "n_candidats_figes": fr["n_candidats_figes"], "n_valides": v["n_valides"], "pbo": v.get("pbo"),
              "n_holdout": hf.get("n_holdout", 0), "n_forward_events": hf.get("n_forward_events", 0),
              "n_pass": rec["n_pass"]}
    (rundir / "resultats" / "pipeline_resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    return resume


def executer_pipeline_donnees_completes(root: Path, rundir: Path, *, code_sha: str,
                                        dossiers=None, ledgers_logs=None,
                                        variantes=None, stop_event=None, predicat=None,
                                        new_events=None, affected_windows=None, hist_dir=None, securise=None,
                                        episodes_prets=None, portefeuille_global_dir=None) -> dict:
    """LOT18H-DATA-COMPLETE : catalogue COMPLET (sans plafond silencieux) → CORPUS canonique réellement
    consommé (provenance + dedup selon la source) → 7 phases → analyse des LOGS (refus rejoués, gate vs
    no-gate) → LIGNÉE des PnL → CSVs d'utilisation. Une source cataloguée ne compte que si elle est CONSOMMÉE."""
    import catalogue_archives_18h as CAT
    import corpus_18h as COR
    import logs_18h as LOGS
    import lineage_18h as LIN
    rundir = Path(rundir)
    if stop_event is not None and stop_event.is_set():       # arrêt coopératif AVANT le catalogage (PT-8)
        (rundir / "resultats").mkdir(parents=True, exist_ok=True)
        resume = {"interrompu": True, "phase": "AVANT_CATALOGUE", "n_fast_screen": 0, "n_survivants": 0, "n_pass": 0}
        (rundir / "resultats" / "pipeline_resume.json").write_text(json.dumps(resume, ensure_ascii=False), encoding="utf-8")
        return resume
    kw = {} if dossiers is None else {"dossiers": dossiers}
    ingestion = {"mode": "FULL"}
    if new_events is None and affected_windows is None:
        # comportement HISTORIQUE (18h) : catalogue complet à chaque appel
        cat = CAT.cataloguer_complet(root, rundir, **kw)
        sources = cat["sources"]
        cons = COR.construire(sources, root=root)
        corpus = cons["episodes"]
    else:
        # INCRÉMENTAL (continu, PT-2) : corpus historique IMMUABLE (cache au niveau RUN) + segments neufs +
        # fenêtre active ; le cycle 2 NE recatalogue PAS et NE rejoue PAS tout l'historique.
        import corpus_incremental as INC
        hd = Path(hist_dir) if hist_dir else rundir
        hist = INC.preparer_historique(root, hd, cataloguer=lambda r, rd: CAT.cataloguer_complet(r, rd, **kw),
                                       construire=COR.construire)
        new_segs = INC.segments_incrementaux(new_events or [])
        fen = INC.fenetre_active(hist["corpus"], new_segs, affected_windows)
        corpus = fen["working"] or hist["corpus"]
        cat = {"sources": [], "accounting": hist["manifest"].get("accounting", {})}
        cons = {"episodes": corpus, "comptes": {"utilises": len(corpus)}}
        # AF-P1 : les épisodes LIVE MÛRIS (FWD_BOOK, promouvables) s'ajoutent au corpus de travail
        prets = list(episodes_prets or [])
        if prets:
            corpus = corpus + prets
        ingestion = {"mode": "INCREMENTAL", "from_cache": hist["from_cache"],
                     "n_sources_parsees_ce_cycle": hist["n_sources_parsees_ce_cycle"],
                     "n_hist_total": fen["n_hist_total"], "n_hist_rejoues": fen["n_hist_rejoues"],
                     "n_new_segments": fen["n_new_segments"], "n_episodes_muris": len(prets),
                     "coins_actifs": fen["coins"]}
        sources = cat["sources"]
    if not corpus:                                         # honnête : pas d'épisode marché exploitable
        corpus = corpus_fixtures()
        cons["comptes"]["fallback"] = "SYNTHETIC (aucun épisode BBO exploitable dans les archives)"
    resume = executer_pipeline_complet(root, rundir, corpus, code_sha=code_sha,
                                       source_hash=(sources[0]["sha256"] if sources and sources[0].get("sha256") else "corpus"),
                                       variantes=variantes, stop_event=stop_event, predicat=predicat, securise=securise,
                                       portefeuille_global_dir=portefeuille_global_dir)
    # analyse des logs / ledgers (refus rejoués + gate vs no-gate)
    if ledgers_logs is None:
        ledgers_logs = _ledgers_logs_par_defaut(root)
    log_res = LOGS.analyser(rundir, ledgers_logs)
    # utilisation des sources par trial + couverture archives/live
    _ecrire_trial_source_usage(rundir, sources, cons["comptes"])
    _ecrire_coverage(rundir, sources, cons["comptes"], log_res)
    # lignée : pour chaque verdict final, une ligne source→…→pnl→rapport
    finals = []
    try:
        finals = json.loads((rundir / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for f in finals:
        LIN.enregistrer(rundir, {"source": (sources[0]["chemin"] if sources else "corpus"),
                                 "evenement": "BBO/TRADE", "feature": f.get("family"), "signal": f.get("trial_id"),
                                 "decision": f.get("verdict"), "execution_paper": "forward_paper.jsonl",
                                 "ledger": "trials_results.jsonl", "pnl": f.get("trial_id"),
                                 "rapport": "RAPPORT-RECHERCHE-18H.md"})
    resume.update({"accounting": cat["accounting"], "corpus_comptes": cons["comptes"], "ingestion": ingestion,
                   "log_analyse": {"n_gaps": log_res["n_gaps"], "gate_vs_nogate": log_res["gate_vs_nogate"]}})
    (rundir / "resultats" / "cycle_ingestion.json").write_text(json.dumps(ingestion, ensure_ascii=False, indent=1), encoding="utf-8")
    (rundir / "resultats" / "pipeline_resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    return resume


def _ledgers_logs_par_defaut(root: Path) -> list:
    """Journaux à analyser (P6) : ledgers paper + logs de collecte/décisions/refus (runtime/data + lab)."""
    root = Path(root)
    out = []
    mots = ("ledger", "decision", "refus", "log", "trials")
    for base in (root / "runtime" / "data", root / "runtime" / "research_lab", root / "logs"):
        if not base.exists():
            continue
        for p in base.rglob("*.jsonl"):
            if any(m in p.name.lower() for m in mots):
                out.append(p)
                if len(out) > 40:
                    return out
    return out


def _ecrire_trial_source_usage(rundir: Path, sources, comptes) -> None:
    import csv
    import io
    tids = []
    p = rundir / "ledger" / "trials_results.jsonl"
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            try:
                tids.append(json.loads(l).get("trial_id"))
            except ValueError:
                continue
    src_list = ";".join(s["chemin"] for s in sources[:20])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["trial_id", "archive_events_used", "live_events_used", "log_events_used", "sources"])
    w.writeheader()
    live = comptes.get("par_type", {}).get("BBO", 0)
    for tid in tids:
        w.writerow({"trial_id": tid, "archive_events_used": comptes.get("utilises", 0),
                    "live_events_used": live, "log_events_used": 0, "sources": src_list})
    (rundir / "results").mkdir(parents=True, exist_ok=True)
    (rundir / "results" / "trial_source_usage.csv").write_text(buf.getvalue(), encoding="utf-8")


def _ecrire_coverage(rundir: Path, sources, comptes, log_res) -> None:
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["dimension", "detectees", "events_lus", "events_utilises", "dedup", "gaps"])
    w.writeheader()
    w.writerow({"dimension": "archives+live", "detectees": len(sources), "events_lus": comptes.get("lus", 0),
                "events_utilises": comptes.get("utilises", 0), "dedup": comptes.get("dedup", 0),
                "gaps": log_res.get("n_gaps", 0)})
    (rundir / "results" / "archive_live_coverage.csv").write_text(buf.getvalue(), encoding="utf-8")


__all__ = ["moteur_exact", "nets_exact", "fast_screen_variante", "generer_variantes", "phase_discovery",
           "phase_freeze", "candidats_geles", "phase_validation", "phase_holdout_forward",
           "reconcilier_et_juger", "corpus_fixtures", "corpus_depuis_archives", "executer_pipeline_complet",
           "executer_pipeline_donnees_completes", "HORIZONS_MS"]
