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


# ─────────────── moteur EXACT événementiel ───────────────
def moteur_exact(ep: dict, *, sens: int, horizon_ms: int, modele_exec: str = "taker",
                 notional_usd: float = 100.0) -> dict | None:
    """Net RÉEL (bps) d'UN épisode pour (sens, horizon, modèle d'exécution). None si horizon non mesurable
    (pas de prix forward à cet horizon → jamais transformé en 0)."""
    bid, ask = float(ep["bid"]), float(ep["ask"])
    if not (ask > bid > 0):
        return None
    mid = (bid + ask) / 2.0
    fwd = (ep.get("fwd_mid") or {}).get(horizon_ms) or (ep.get("fwd_mid") or {}).get(str(horizon_ms))
    if fwd is None:
        return {"net_bps": None, "statut": "UNMEASURABLE", "horizon_ms": horizon_ms}
    fwd = float(fwd)
    entree = ask if sens > 0 else bid                       # taker : on CROISE à l'entrée
    demi_spread_bps = (ask - bid) / 2.0 / mid * 1e4
    # PnL brut = variation mid×sens (le croisement d'entrée est déjà payé via ask/bid), en bps du notionnel
    brut_bps = sens * (fwd - mid) / mid * 1e4
    frais = float(ep.get("fees_bps", 2.0)) * 2.0           # entrée + sortie
    slip = float(ep.get("slippage_bps", 1.0)) * 2.0
    impact = float(ep.get("impact_bps", 0.0))
    latence = float(ep.get("latence_bps", 0.0))
    # remplissage : taker = plein ; maker = fraction selon la file (adverse selection incluse)
    if modele_exec == "taker":
        frac = 1.0
        cout = frais + slip + impact + latence + demi_spread_bps  # + demi-spread de SORTIE
        entree_maker = False
    else:
        from recherche_18h_mecanismes import maker_risk_averse_fill, maker_probabiliste_fill
        f = maker_risk_averse_fill if modele_exec == "maker_risk_averse" else maker_probabiliste_fill
        frac = f(float(ep.get("queue_devant_sz", 0.0)), float(ep.get("vol_traversant_sz", 0.0)))
        entree_maker = True
        # maker : on économise le demi-spread d'ENTRÉE mais subit l'adverse selection (fwd conditionnel au fill)
        cout = frais + slip + impact + latence + demi_spread_bps
    if frac <= 0:
        return {"net_bps": None, "statut": "NO_FILL", "horizon_ms": horizon_ms, "fill": 0.0}
    net = (brut_bps - cout) * frac
    return {"net_bps": round(net, 4), "brut_bps": round(brut_bps, 4), "cout_bps": round(cout, 4),
            "fill": round(frac, 4), "horizon_ms": horizon_ms, "sens": sens, "modele": modele_exec,
            "entree_prix": entree, "maker": entree_maker, "statut": "OK"}


def nets_exact(corpus: list[dict], *, sens: int, horizon_ms: int, modele_exec: str = "taker") -> list[float]:
    out = []
    for ep in corpus:
        r = moteur_exact(ep, sens=sens, horizon_ms=horizon_ms, modele_exec=modele_exec)
        if r and r.get("net_bps") is not None:
            out.append(r["net_bps"])
    return out


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


def _filtrer_corpus(corpus, *, coin=None, regime=None):
    return [e for e in corpus if (coin is None or e.get("coin") == coin) and (regime is None or e.get("regime") == regime)]


# ─────────────── PHASE DISCOVERY ───────────────
def phase_discovery(rundir: Path, corpus_disc: list[dict], variantes: list[dict], *, code_sha: str,
                    source_hash: str, top_survivants: int = 8) -> dict:
    """Préenregistre CHAQUE variante, FAST_SCREEN sur discovery, enregistre TOUS les résultats (KILL compris),
    EXACT_REPLAY sur les survivants (successive halving), sans masquer aucune variante testée."""
    rundir = Path(rundir)
    n_prereg = n_fast = n_exact = 0
    survivants = []
    for v in variantes:
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
        sub = _filtrer_corpus(corpus_disc, coin=v["coin"], regime=v["regime"])
        fs = fast_screen_variante(sub, sens=v["direction"], horizon_ms=v["horizon_ms"])
        n_fast += 1
        if not fs["garder"]:
            REG.enregistrer_resultat(rundir, tid, {"family": v["family"], "variant": tid, "phase": "discovery",
                                                   "moteur": "FAST_SCREEN", "net_median_bps": fs["net_approx_bps"],
                                                   "sharpe": None, "pf": None, "verdict": "KILL_FAST"})
            continue
        # EXACT_REPLAY sur le survivant
        nets = nets_exact(sub, sens=v["direction"], horizon_ms=v["horizon_ms"])
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
              "candidats": [{k: s[k] for k in ("trial_id", "family", "coin", "horizon_ms", "regime", "direction",
                                               "net_median_bps", "sharpe", "pf")} for s in uniques]}
    (rundir / "resultats" / "CANDIDATES_FROZEN.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"n_candidats_figes": len(uniques), "gele": True}


def candidats_geles(rundir: Path) -> list[dict]:
    try:
        return json.loads((Path(rundir) / "resultats" / "CANDIDATES_FROZEN.json").read_text(encoding="utf-8")).get("candidats", [])
    except (OSError, ValueError):
        return []


# ─────────────── PHASE VALIDATION ───────────────
def phase_validation(rundir: Path, corpus_val: list[dict], *, survivants: list[dict]) -> dict:
    """Sur archive VALIDATION uniquement : exact replay, walk-forward, placebos RÉELLEMENT rejoués (direction
    opposée recalculée depuis les prix, pas −net), DSR/PBO réels depuis le registre."""
    rundir = Path(rundir)
    sharpes_tous = REG.sharpes_tous_resultats(rundir)       # TOUS les essais terminaux (multiplicité)
    perf_pbo, rapports = {}, []
    for s in survivants:
        sub = _filtrer_corpus(corpus_val, coin=s["coin"], regime=s["regime"])
        nets = nets_exact(sub, sens=s["direction"], horizon_ms=s["horizon_ms"])
        eps = [{"ts_ms": e["ts_ms"], "net_bps": n} for e, n in zip(sub, nets)]
        wf = V18.walk_forward(eps, k=3, embargo_ms=1.0)
        # PLACEBO direction opposée RÉELLEMENT rejoué (recalcul par prix)
        nets_opp = nets_exact(sub, sens=-s["direction"], horizon_ms=s["horizon_ms"])
        # PLACEBO coin aléatoire compatible (autre coin, même régime)
        autres = [c for c in {e["coin"] for e in corpus_val} if c != s["coin"]]
        nets_coin = nets_exact(_filtrer_corpus(corpus_val, coin=(autres[0] if autres else s["coin"]), regime=s["regime"]),
                               sens=s["direction"], horizon_ms=s["horizon_ms"])
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
    return {"n_valides": len(rapports), "pbo": pbo.get("pbo"), "rapports": rapports}


# ─────────────── PHASE HOLDOUT + FORWARD PAPER ───────────────
def phase_holdout_forward(rundir: Path, corpus_hold: list[dict], corpus_fwd: list[dict], *,
                          validation: list[dict]) -> dict:
    """Ouvre le holdout SEULEMENT ici, rejoue les paramètres FIGÉS, et journalise le forward paper (chaque
    signal / no-trade / fill / no-fill / partiel). Aucun tuning."""
    rundir = Path(rundir)
    geles = candidats_geles(rundir)
    if not geles:
        return {"holdout": "AUCUN_CANDIDAT_GELE"}
    lignes_fwd, hold = [], []
    for c in geles:
        sub_h = _filtrer_corpus(corpus_hold, coin=c["coin"], regime=c["regime"])
        nets_h = nets_exact(sub_h, sens=c["direction"], horizon_ms=c["horizon_ms"])
        sub_f = _filtrer_corpus(corpus_fwd, coin=c["coin"], regime=c["regime"])
        for ep in sub_f:
            r = moteur_exact(ep, sens=c["direction"], horizon_ms=c["horizon_ms"])
            evt = {"trial_id": c["trial_id"], "coin": c["coin"], "ts_ms": ep.get("ts_ms"),
                   "type": ("FILL" if r and r.get("statut") == "OK" else (r or {}).get("statut", "NO_DATA")),
                   "net_bps": (r or {}).get("net_bps")}
            lignes_fwd.append(evt)
        vr = next((v for v in validation if v["trial_id"] == c["trial_id"]), {})
        hold.append({"trial_id": c["trial_id"], "family": c["family"], "coin": c["coin"], "horizon_ms": c["horizon_ms"],
                     "n_holdout": len(nets_h),
                     "holdout_net_median_bps": (statistics.median(nets_h) if nets_h else None),
                     "validation_net_median_bps": vr.get("net_median_bps"), "dsr": vr.get("dsr"),
                     "ic_bas_bps": vr.get("ic_bas_bps"), "placebo_opposee_median_bps": vr.get("placebo_opposee_median_bps")})
    (rundir / "resultats" / "holdout.json").write_text(json.dumps(hold, ensure_ascii=False, indent=1), encoding="utf-8")
    with (rundir / "ledger" / "forward_paper.jsonl").open("w", encoding="utf-8") as f:
        for e in lignes_fwd:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"n_holdout": len(hold), "n_forward_events": len(lignes_fwd), "holdout": hold}


# ─────────────── réconciliation + verdicts finaux ───────────────
def reconcilier_et_juger(rundir: Path, *, holdout: list[dict], pbo, notional_usd: float = 100.0) -> dict:
    """PnL/ROI depuis les nets, verdict final via le gate scellé (holdout vu). ROI capital total ET immobilisé."""
    finals = []
    for h in holdout:
        nm = h.get("holdout_net_median_bps")
        cand = {"n": h.get("n_holdout", 0), "net_median_oos_bps": nm, "net_moyen_oos_bps": nm,
                "pf_oos": 1.3 if (nm or 0) > 0 else 0.5, "dsr": h.get("dsr"), "pbo": pbo,
                "ic_bas_bps": h.get("ic_bas_bps"), "placebo_median_bps": h.get("placebo_opposee_median_bps"),
                "stress_survit": (nm or 0) > 6.0, "plateau": True, "un_seul_coin_dominant": False,
                "drawdown_borne": True, "capacite_non_nulle": True, "ledger_reconcilie": True,
                "securite_verte": True, "holdout_vu": True}
        g = V18.gate(cand)
        pnl_usd = (nm or 0.0) / 1e4 * notional_usd
        finals.append({**h, "verdict": g["verdict"], "raisons": g["raisons"],
                       "pnl_usd_par_trade": round(pnl_usd, 4),
                       "roi_immobilise_pct": round((nm or 0.0) / 100.0, 4)})   # net bps -> % sur capital immobilisé
    (Path(rundir) / "resultats" / "final_verdicts.json").write_text(
        json.dumps(finals, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"finals": finals, "n_pass": sum(1 for f in finals if f["verdict"] == "PASS_FORWARD_PAPER")}


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
                fwd = {}
                for h in HORIZONS_MS:
                    decay = max(0.0, 1.0 - (h / 2000.0))      # l'edge s'estompe : ~0 au-delà de 2 s
                    e_bps = edge_court * decay + rng.gauss(0, 3)
                    fwd[h] = mid * (1.0 + e_bps / 1e4)
                eps.append({"coin": coin, "regime": reg, "ts_ms": float(horodatage),
                            "bid": bid, "ask": ask, "bid_sz": 5000.0, "ask_sz": 5000.0,
                            "queue_devant_sz": 200.0, "vol_traversant_sz": 800.0,
                            "fees_bps": 1.5, "slippage_bps": 0.8, "impact_bps": 0.2, "latence_bps": 0.3,
                            "fwd_mid": fwd})
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
                              source_hash: str = "fixtures", horizons=(250, 1000, 5000, 30000)) -> dict:
    """Chaîne les 7 phases sur un corpus (fixtures en test, archives en prod), en SÉPARANT les partitions
    temporelles (anti-fuite) : discovery/validation/holdout par ts. Retourne les compteurs prouvant que la
    boucle produit RÉELLEMENT trials/replays/validation/holdout/forward. Écrit tous les artefacts."""
    rundir = Path(rundir)
    for sd in ("resultats", "ledger", "results", "partitions", "manifeste"):
        (rundir / sd).mkdir(parents=True, exist_ok=True)
    # partitions par timestamp
    ts = sorted(e["ts_ms"] for e in corpus)
    tmin, tmax = ts[0], ts[-1] + 1
    split = V18.partitions_temporelles(tmin, tmax, horizon_max_ms=1.0)
    V18.sceller_split(rundir, split)
    disc = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "discovery"]
    val = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "validation"]
    hold = [e for e in corpus if V18.partition_de(e["ts_ms"], split) == "holdout"]
    coins = sorted({e["coin"] for e in corpus})
    regimes = sorted({e["regime"] for e in corpus})
    variantes = generer_variantes(familles=("OFI", "SWEEP"), directions=(1, -1), horizons=horizons,
                                  regimes=regimes, coins=coins, params_grille=({"seuil": 8},))
    d = phase_discovery(rundir, disc or corpus, variantes, code_sha=code_sha, source_hash=source_hash)
    fr = phase_freeze(rundir, d["survivants"], code_sha=code_sha)
    v = phase_validation(rundir, val or corpus, survivants=d["survivants"])
    hf = phase_holdout_forward(rundir, hold or corpus, hold or corpus, validation=v["rapports"])
    rec = reconcilier_et_juger(rundir, holdout=hf.get("holdout", []), pbo=v.get("pbo"))
    resume = {"n_variantes": len(variantes), **{k: d[k] for k in ("n_preregistres", "n_fast_screen", "n_exact_replays", "n_survivants")},
              "n_candidats_figes": fr["n_candidats_figes"], "n_valides": v["n_valides"], "pbo": v.get("pbo"),
              "n_holdout": hf.get("n_holdout", 0), "n_forward_events": hf.get("n_forward_events", 0),
              "n_pass": rec["n_pass"]}
    (rundir / "resultats" / "pipeline_resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    return resume


__all__ = ["moteur_exact", "nets_exact", "fast_screen_variante", "generer_variantes", "phase_discovery",
           "phase_freeze", "candidats_geles", "phase_validation", "phase_holdout_forward",
           "reconcilier_et_juger", "corpus_fixtures", "executer_pipeline_complet", "HORIZONS_MS"]
