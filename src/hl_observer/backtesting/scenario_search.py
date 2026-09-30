"""Recherche MASSIVE de scenarios sur les donnees replay enregistrees (a lancer APRES les 48h).

Essaie des dizaines de milliers de reglages (scenario_grid) avec la discipline anti-overfit :
  1. eval RAPIDE et FIDELE : reutilise simulate_exit_on_path (no-lookahead) ; PnL sur NOTRE
     taille reelle (notional_usd, defaut 500 = marge $50 x levier 10) ; cout = fees+spread +
     degradation de copie REELLE enregistree par candidat ; filtre d'edge d'entree ;
  2. split TEMPOREL train/test ;
  3. classement sur train, re-eval du top-K sur le TEST (out-of-sample) ;
  4. 'robuste' = net>0 train ET test ET gate DEPLOY_CANDIDATE ET plateau (voisinage sain).
Parallelise (tous les coeurs). REPLAY-only : lit des fichiers, ecrit un rapport, ne touche
jamais au ledger live, aucun ordre. Metriques descriptives ; aucune promesse de PnL.
"""

from __future__ import annotations

import json
import math

from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin, simulate_exit_on_path
from hl_observer.backtesting.anti_overfit_gate import evaluer as _anti_overfit
from hl_observer.backtesting.purged_split import purged_temporal_split
from hl_observer.backtesting.scenario_grid import generate
from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.ops.echec_silencieux import noter as _noter_echec

CONTEXT = "REPLAY"
DEFAULT_NOTIONAL_USD = 500.0  # notre position reelle = marge $50 x levier 10


def _config_for(sc) -> SLTPConfig:
    trail = sc.trailing_stop_bps if sc.trailing_stop_bps > 0 else None
    act = sc.trailing_activation_bps if (trail and sc.trailing_activation_bps > 0) else None
    sl = float(sc.sl_bps)
    # Stop catastrophe = plafond de perte dur. SLTPConfig n'a pas de champ dedie (module live
    # non touche) => on l'exprime via stop_loss = min(sl, catastrophe) quand il est actif.
    cat = float(getattr(sc, "catastrophic_stop_bps", 0.0) or 0.0)
    if cat > 0:
        sl = min(sl, cat)
    return SLTPConfig(
        stop_loss_bps=sl, take_profit_bps=float(sc.tp_bps),
        trailing_stop_bps=trail, trailing_activation_bps=act,
        breakeven_buffer_bps=float(sc.breakeven_bps),
    )


def eval_trades(sc, candidates, marks, notional_usd=DEFAULT_NOTIONAL_USD):
    cfg = _config_for(sc)
    hz = float(sc.horizon_min)
    min_edge = float(sc.min_edge_bps)
    base_cost = float(sc.cost_bps)
    notl = float(notional_usd)
    # --- 7 filtres d'entree (dimensions additionnelles), mappes aux champs REELS des candidats ---
    max_age = float(getattr(sc, "max_signal_age_ms", 0.0) or 0.0)          # fraicheur (ms)
    min_liq = float(getattr(sc, "min_liquidity_score", 0.0) or 0.0)        # liquidite 0..1
    if min_liq > 1.0:  # compat: valeurs 0..100 heritees d'anciennes DB -> ramenees a 0..1
        min_liq /= 100.0
    min_cons = int(getattr(sc, "min_consensus_wallets", 1) or 1)           # consensus wallets
    max_deg = float(getattr(sc, "max_copy_degradation_bps", 0.0) or 0.0)   # plafond degradation copie (bps)
    min_ls = float(getattr(sc, "min_leader_score", 0.0) or 0.0)           # score leader
    side_mode = str(getattr(sc, "side_mode", "both") or "both")           # both | long_only | short_only
    return [pnl for _coin, _ts, pnl in _eval_pairs(
        candidates, marks, cfg, hz, min_edge, base_cost, notl,
        max_age, min_liq, min_cons, max_deg, min_ls, side_mode,
    )]


def eval_trades_triplets(sc, candidates, marks, notional_usd=DEFAULT_NOTIONAL_USD):
    """MEME evaluation, mais on GARDE le `ts` d'entree : (coin, ts, pnl).

    #595 — c'est ce qui permet d'ETIQUETER le regime de chaque trade sans rien inventer :
    le `ts` etait deja calcule dans `_eval_pairs` (`entry_ts`), il etait simplement JETE.

    ⚠️ A n'utiliser QUE sur les ~40 finalistes, jamais dans la boucle qui balaie les 150 M.
    """
    cfg = _config_for(sc)
    min_liq = float(getattr(sc, "min_liquidity_score", 0.0) or 0.0)
    if min_liq > 1.0:
        min_liq /= 100.0
    return list(_eval_pairs(
        candidates, marks, cfg, float(sc.horizon_min), float(sc.min_edge_bps),
        float(sc.cost_bps), float(notional_usd),
        float(getattr(sc, "max_signal_age_ms", 0.0) or 0.0), min_liq,
        int(getattr(sc, "min_consensus_wallets", 1) or 1),
        float(getattr(sc, "max_copy_degradation_bps", 0.0) or 0.0),
        float(getattr(sc, "min_leader_score", 0.0) or 0.0),
        str(getattr(sc, "side_mode", "both") or "both"),
    ))


def eval_trades_by_coin(sc, candidates, marks, notional_usd=DEFAULT_NOTIONAL_USD):
    """MEME evaluation que eval_trades, mais GROUPEE PAR COIN.

    Pourquoi : `net_total_usd` (la somme) peut etre porte par UN SEUL marche chanceux.
    Pour savoir si une config tient PARTOUT, il faut le net du PIRE marche -- pas la somme.
    Aucun changement de comportement : meme filtres, meme simulate_exit_on_path.
    """
    cfg = _config_for(sc)
    max_age = float(getattr(sc, "max_signal_age_ms", 0.0) or 0.0)
    min_liq = float(getattr(sc, "min_liquidity_score", 0.0) or 0.0)
    if min_liq > 1.0:
        min_liq /= 100.0
    out: dict[str, list[float]] = {}
    for coin, _ts, pnl in _eval_pairs(
        candidates, marks, cfg, float(sc.horizon_min), float(sc.min_edge_bps),
        float(sc.cost_bps), float(notional_usd), max_age, min_liq,
        int(getattr(sc, "min_consensus_wallets", 1) or 1),
        float(getattr(sc, "max_copy_degradation_bps", 0.0) or 0.0),
        float(getattr(sc, "min_leader_score", 0.0) or 0.0),
        str(getattr(sc, "side_mode", "both") or "both"),
    ):
        out.setdefault(coin, []).append(pnl)
    return out


def _eval_pairs(candidates, marks, cfg, hz, min_edge, base_cost, notl,
                max_age, min_liq, min_cons, max_deg, min_ls, side_mode):
    """Coeur d'evaluation : rend **(coin, ts, pnl)**.

    Extraction pure, sans changement de logique. `eval_trades()` jette le coin ET le ts,
    `eval_trades_by_coin()` garde le coin, `eval_trades_triplets()` garde tout.
    Un seul chemin de code -> ils ne peuvent pas diverger.

    #595 (13/07) : le `ts` d'entree etait DEJA calcule ici (`entry_ts=ts`) et simplement JETE.
    Le rendre permet d'ETIQUETER le regime de chaque trade sans inventer une seule donnee.
    """
    for c in candidates:
        if min_edge > 0:
            edge = c.get("edge_remaining_bps")
            if edge is None or float(edge) < min_edge:
                continue
        coin = str(c.get("coin") or "").upper()
        side = str(c.get("direction") or "").upper()
        entry = float(c.get("current_mid") or 0.0)
        ts = float(c.get("recorded_at") or 0.0)
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        # sens autorise
        if side_mode == "long_only" and side != "LONG":
            continue
        if side_mode == "short_only" and side != "SHORT":
            continue
        # fraicheur du signal (donnee manquante + filtre actif => refus, deny-by-default)
        if max_age > 0:
            age = c.get("signal_age_ms")
            if age is None or float(age) > max_age:
                continue
        # liquidite (score 0..1)
        if min_liq > 0:
            liq = c.get("liquidity_score")
            if liq is None or float(liq) < min_liq:
                continue
        # consensus de wallets
        if min_cons > 1:
            cons = c.get("consensus_wallets")
            if cons is None or int(cons) < min_cons:
                continue
        # score du leader (priorite baleines)
        if min_ls > 0:
            ls = c.get("leader_score")
            if ls is None or float(ls) < min_ls:
                continue
        # degradation de copie : plafond d'entree + ajoutee au cout
        deg = abs(float(c.get("copy_degradation_bps") or 0.0))
        if max_deg > 0 and deg > max_deg:
            continue
        cost = base_cost + deg
        pnl = simulate_exit_on_path(
            side=side, entry_price=entry, path=marks.get(coin, []), entry_ts=ts,
            config=cfg, horizon_min=hz, cost_bps=cost, notional_usd=notl,
        )
        if pnl is not None:
            yield coin, ts, pnl


def report_from_trades(trades):
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "profit_factor": round(pf, 4) if pf != float("inf") else "inf",
        "net_total_usd": round(sum(trades), 4),
        "max_drawdown_usd": round(dd, 4),
        "avg_trade_usd": round(sum(trades) / len(trades), 6) if trades else None,
    }


def temporal_split(candidates, train_frac=0.7):
    cs = sorted(candidates, key=lambda c: float(c.get("recorded_at") or 0.0))
    if len(cs) <= 1:
        return cs, []
    k = max(1, min(len(cs) - 1, int(len(cs) * float(train_frac))))
    return cs[:k], cs[k:]


def prefilter_candidates(candidates, marks):
    """Garde UNIQUEMENT les candidats qui peuvent trader : coin present dans marks, side/entry/ts
    valides, et au moins un mark POSTERIEUR a l'entree. Scenario-INDEPENDANT => applique UNE fois
    avant la recherche. Resultats identiques (eval_trades les aurait ecartes), mais enorme gain de
    vitesse a l'echelle (on ne re-scanne pas les non-mesurables pour chaque scenario)."""
    out = []
    for c in candidates:
        coin = str(c.get("coin") or "").upper()
        side = str(c.get("direction") or "").upper()
        try:
            entry = float(c.get("current_mid") or 0.0)
            ts = float(c.get("recorded_at") or 0.0)
        except (TypeError, ValueError):
            continue
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        path = marks.get(coin)
        if not path or path[-1][0] <= ts:  # aucun mark posterieur => non mesurable
            continue
        out.append(c)
    return out


_SHARED = {}


def _init_worker(train, marks, notional):
    _SHARED["train"] = train
    _SHARED["marks"] = marks
    _SHARED["notional"] = notional


def _eval_worker(sc):
    return sc, report_from_trades(eval_trades(sc, _SHARED["train"], _SHARED["marks"], _SHARED["notional"]))


def _score_all(scenarios, train, marks, min_trades, jobs, notional):
    if jobs and int(jobs) > 1:
        try:
            import concurrent.futures as cf
            with cf.ProcessPoolExecutor(max_workers=int(jobs), initializer=_init_worker,
                                        initargs=(train, marks, notional)) as ex:
                pairs = list(ex.map(_eval_worker, scenarios, chunksize=64))
            return [(sc, rep) for sc, rep in pairs if (rep["trades"] or 0) >= min_trades]
        except Exception:
            _noter_echec("hl_observer/backtesting/scenario_search.py:247")
    out = []
    for sc in scenarios:
        rep = report_from_trades(eval_trades(sc, train, marks, notional))
        if (rep["trades"] or 0) >= min_trades:
            out.append((sc, rep))
    return out


def _scenario_row(sc):
    return {
        "name": sc.name, "source": sc.source, "sl_bps": sc.sl_bps, "tp_bps": sc.tp_bps,
        "trailing_stop_bps": sc.trailing_stop_bps, "trailing_activation_bps": sc.trailing_activation_bps,
        "breakeven_bps": sc.breakeven_bps, "horizon_min": sc.horizon_min,
        "cost_bps": sc.cost_bps, "min_edge_bps": sc.min_edge_bps,
        # 7 dimensions additionnelles (le gagnant doit exposer sa config complete)
        "max_signal_age_ms": getattr(sc, "max_signal_age_ms", None),
        "min_liquidity_score": getattr(sc, "min_liquidity_score", None),
        "min_consensus_wallets": getattr(sc, "min_consensus_wallets", None),
        "max_copy_degradation_bps": getattr(sc, "max_copy_degradation_bps", None),
        "min_leader_score": getattr(sc, "min_leader_score", None),
        "side_mode": getattr(sc, "side_mode", None),
        "catastrophic_stop_bps": getattr(sc, "catastrophic_stop_bps", None),
    }


def _norm_vec(sc):
    return (sc.sl_bps / 130.0, sc.tp_bps / 420.0, sc.trailing_stop_bps / 220.0,
            sc.horizon_min / 480.0, sc.min_edge_bps / 60.0)


def _plateau_flag(sc, scored_map, k=12):
    v = _norm_vec(sc)
    dists = [(math.dist(v, _norm_vec(other)), net) for other, net in scored_map]
    dists.sort(key=lambda x: x[0])
    nets = [net for _, net in dists[1:k + 1]]
    if not nets:
        return False
    nets.sort()
    return nets[len(nets) // 2] > 0.0


def search(candidates, mark_rows, scenarios, *, train_frac=0.7, top_k=40, min_trades=25,
           jobs=1, notional_usd=DEFAULT_NOTIONAL_USD):
    from hl_observer.backtesting.validation_gates import run_validation_gates

    from hl_observer.backtesting import regime_wiring as _rw

    marks = marks_by_coin(mark_rows)

    # 🔴 #410 / H-05 + #435 / H-30 -- LA COUPE TRAIN/TEST FUYAIT (corrige le 2026-07-13).
    #
    # AVANT : `temporal_split` coupait a l'index k. **AUCUNE purge, AUCUN embargo.**
    # Un candidat en fin de TRAIN ouvre un trade dont la SORTIE arrive jusqu'a **8 HEURES** plus
    # tard -- donc **DANS la periode de TEST**. Son PnL d'entrainement etait calcule avec des prix
    # du test... et c'est sur ce train contamine qu'on CHOISISSAIT la config SL/TP.
    #
    #     **Le test etait deja dans le train.** On mesurait « hors echantillon » un choix fait
    #     AVEC l'echantillon.
    #
    # `purged_walk_forward_splits` (IDEA-30) existait POUR CA. **Il etait mort** -- comme les six
    # autres garde-fous anti-overfit (M-19). *H-05/H-30 pointaient un bug chez NOUS.*
    #
    # ⚠️ ON PREND LE PIRE HORIZON DE LA GRILLE, pas le moyen : **une seule config qui fuit suffit
    # a contaminer la selection.**
    _h_max = max((float(getattr(sc, "horizon_min", 0.0) or 0.0) for sc in scenarios), default=0.0)
    _coupe = purged_temporal_split(candidates, train_frac=train_frac, horizon_min=_h_max)
    train, test = _coupe.train, _coupe.test

    scored = _score_all(scenarios, train, marks, min_trades, jobs, notional_usd)
    scored.sort(key=lambda r: (r[1]["net_total_usd"] or 0.0), reverse=True)
    scored_map = [(sc, (rep["net_total_usd"] or 0.0)) for sc, rep in scored]

    # #595 — LE REGIME, ENFIN BRANCHE.
    #
    # Le seuil HAUTE/BASSE vol se calcule sur le TRAIN SEUL : la fin du train est le dernier
    # `recorded_at` des candidats d'entrainement. Calculer ce seuil sur tout l'echantillon serait
    # un lookahead discret mais reel -- le seuil connaitrait le test.
    #
    # ⚠️ PERF : `preparer()` tourne UNE seule fois, ici, APRES la boucle qui balaie les scenarios.
    # Les ~40 finalistes se partagent ce travail. Rien de tout ceci n'entre dans `_score_all`.
    fin_du_train_ts = max((float(c.get("recorded_at") or 0.0) for c in train), default=0.0)
    prep = _rw.preparer(marks, fin_du_train_ts)

    finalists = []
    for sc, train_rep in scored[:max(1, int(top_k))]:
        triplets = eval_trades_triplets(sc, test, marks, notional_usd)
        test_trades_labellises = _rw.etiqueter_triplets(prep, triplets)
        test_trades = [t["net_pnl_usdc"] for t in test_trades_labellises]
        test_rep = report_from_trades(test_trades)
        # On passe les trades ETIQUETES : `_pnls` lit `net_pnl_usdc`, donc AUCUN autre gate ne
        # change de comportement. Seul `regime_robustness_gate` a enfin de quoi travailler.
        gate = run_validation_gates(test_trades_labellises)
        plateau = _plateau_flag(sc, scored_map)

        # 🔴 #395 / M-19 -- LE GARDE-FOU QUI MANQUAIT (branche le 2026-07-13).
        #
        # Le critere `robust` ne corrigeait **PAS LA MULTIPLICITE**. C'est LE probleme quand on
        # balaie des millions de configurations : **le meilleur d'un tres grand nombre de tirages
        # a l'air genial MEME SI TOUT EST DU BRUIT.** Le holdout OOS aide, mais en SELECTIONNANT
        # le meilleur sur le test, on sur-ajuste le test lui-meme.
        #
        # H-181 avait deja trouve le symptome (« on selectionne les 40 plus CHANCEUSES ») **sans
        # voir que les 7 garde-fous censes l'attraper (deflated_sharpe, White's Reality Check,
        # PBO, purged CV, min_track_record_length...) etaient TOUS MORTS : zero appelant.**
        anti = _anti_overfit(test_trades, n_essais=len(scored))

        robust = bool(
            (train_rep["net_total_usd"] or 0.0) > 0.0
            and (test_rep["net_total_usd"] or 0.0) > 0.0
            and gate.get("verdict") == "DEPLOY_CANDIDATE"
            and plateau
            and anti.survit                       # <-- LE 5e CRITERE. Il manquait.
        )
        finalists.append({
            "scenario": _scenario_row(sc),
            "train": {kk: train_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "test": {kk: test_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "gate_verdict": gate.get("verdict"),
            "plateau": plateau,
            "anti_overfit": anti.as_dict(),
            "robust": robust,
            # VERITE DES DONNEES : on DIT combien de trades sont tombes dans chaque regime.
            # Un `INCONNU` massif est un AVEU (pas assez d'historique), pas un detail cosmetique.
            "regimes": _rw.repartition(test_trades_labellises),
        })

    finalists.sort(key=lambda f: (f["test"]["net_total_usd"] or 0.0), reverse=True)
    robust = [f for f in finalists if f["robust"]]
    return {
        "context": CONTEXT,
        "honesty": "metriques descriptives ; no-lookahead + notre notional + couts reels + train/test + voisinage ; aucune promesse de PnL",
        "notional_usd": notional_usd,
        "candidates_total": len(candidates),
        "train_size": len(train), "test_size": len(test), "train_frac": train_frac,
        # 🔴 LA COUPE DIT CE QU'ELLE A JETE. Une purge silencieuse serait une purge inutile :
        # personne ne saurait que le chiffre d'avant etait FAUX.
        "coupe_purgee": _coupe.as_dict(),
        "scenarios_evaluated": len(scenarios),
        "scenarios_with_min_trades": len(scored),
        "robust_count": len(robust),
        "best_robust": robust[0] if robust else None,
        "finalists": finalists,
        "note": "Fiable seulement si 'robust': net>0 train ET test ET gate ET plateau.",
    }


def search_over_db(candidates, mark_rows, db_path, *, sample=None, batch=50000,
                   train_frac=0.7, top_k=40, min_trades=25, jobs=1,
                   notional_usd=DEFAULT_NOTIONAL_USD, pool=None,
                   max_seconds=None, progress_every=0, stop_file=None, start_id=0,
                   horizon_max_min=480.0):
    """Recherche STREAMING depuis une DB SQLite de scenarios (memoire bornee, pour 10M-150M+).

    Lit les scenarios par LOTS depuis la DB, evalue sur TRAIN, ne garde qu'un POOL des meilleurs
    (heap) => memoire CONSTANTE. Puis OOS (test) + gates + plateau sur le top-K. Meme forme de
    rapport que search(). Le 'plateau' est APPROXIME (voisinage limite au pool). REPLAY-only,
    no-lookahead, notre notional, couts reels. Aucun ordre, aucune promesse de PnL.
    """
    import heapq

    from hl_observer.backtesting.scenario_db import iter_db_scenarios
    from hl_observer.backtesting.validation_gates import run_validation_gates

    from hl_observer.backtesting import regime_wiring as _rw

    marks = marks_by_coin(mark_rows)
    candidates = prefilter_candidates(candidates, marks)  # ecarte les non-mesurables (1 seule fois)

    # 🔴 #410 / H-05 -- LA MEME PURGE ICI. *Une jambe reparee et l'autre laissee, c'est une jambe
    # laissee* (le poller L2 nous l'a deja appris : funding repare le 08/07, carnet laisse).
    #
    # ⚠️ Ce chemin balaie la DB par LOTS : les scenarios arrivent en flux. On ne peut donc pas
    # prendre `max(horizon)` sur toute la grille -- on prend le PLAFOND de la grille, qui est une
    # borne HAUTE. Purger un peu trop est honnete ; purger un peu trop peu ne l'est pas.
    _h_max = float(horizon_max_min or 480.0)
    _coupe = purged_temporal_split(candidates, train_frac=train_frac, horizon_min=_h_max)
    train, test = _coupe.train, _coupe.test
    keep = int(pool or max(int(top_k) * 20, 1000))
    heap = []  # (train_net, counter, sc, train_rep)

    # #595 — MEME etiquetage que dans search(), MEME discipline : seuil sur le TRAIN SEUL, et
    # `preparer()` tourne UNE fois, hors de la boucle de scoring qui balaie les 150 M.
    fin_du_train_ts = max((float(c.get("recorded_at") or 0.0) for c in train), default=0.0)
    prep = _rw.preparer(marks, fin_du_train_ts)

    def _batches():
        bs = []
        for sc in iter_db_scenarios(db_path, limit=sample, start_id=start_id):
            bs.append(sc)
            if len(bs) >= int(batch):
                yield bs
                bs = []
        if bs:
            yield bs

    def _collect(parallel):
        import time as _t
        heap.clear()
        st = {"counter": 0, "evaluated": 0, "kept": 0}
        t0 = _t.time()
        nxt = [int(progress_every) if progress_every else 0]

        def _consume(pairs):
            for sc, rep in pairs:
                st["evaluated"] += 1
                if (rep["trades"] or 0) >= int(min_trades):
                    st["kept"] += 1
                    net = rep["net_total_usd"] or 0.0
                    if len(heap) < keep:
                        heapq.heappush(heap, (net, st["counter"], sc, rep))
                        st["counter"] += 1
                    elif net > heap[0][0]:
                        heapq.heapreplace(heap, (net, st["counter"], sc, rep))
                        st["counter"] += 1
                if progress_every and st["evaluated"] >= nxt[0]:
                    nxt[0] += int(progress_every)
                    bn = max((h[0] for h in heap), default=0.0)
                    print("[replay] evaluated=%d kept=%d elapsed_s=%d best_train_net=%.2f"
                          % (st["evaluated"], st["kept"], _t.time() - t0, bn), flush=True)

        def _should_stop():
            # (1) limite de temps optionnelle ; (2) fichier-signal STOP (arret sur commande).
            if max_seconds and (_t.time() - t0) > float(max_seconds):
                return True
            if stop_file:
                try:
                    import os as _os
                    if _os.path.exists(str(stop_file)):
                        return True
                except Exception:
                    _noter_echec("hl_observer/backtesting/scenario_search.py:478")
            return False

        if parallel:
            import concurrent.futures as cf
            # UN SEUL pool pour toute la recherche : les workers recoivent train/marks UNE fois
            # (initializer) -> pas de re-pickle par lot. Indispensable a l'echelle 150M.
            with cf.ProcessPoolExecutor(max_workers=int(jobs), initializer=_init_worker,
                                        initargs=(train, marks, notional_usd)) as ex:
                for bs in _batches():
                    _consume(ex.map(_eval_worker, bs, chunksize=64))
                    if _should_stop():
                        break
        else:
            for bs in _batches():
                _consume((sc, report_from_trades(eval_trades(sc, train, marks, notional_usd)))
                         for sc in bs)
                if _should_stop():
                    break
        return st

    try:
        _st = _collect(bool(jobs and int(jobs) > 1))
    except Exception:
        _st = _collect(False)  # repli mono-process, etat remis a zero (pas de double comptage)
    evaluated = _st["evaluated"]
    kept = _st["kept"]

    scored = [(sc, rep) for (_n, _c, sc, rep) in heap]
    scored.sort(key=lambda r: (r[1]["net_total_usd"] or 0.0), reverse=True)
    scored_map = [(sc, (rep["net_total_usd"] or 0.0)) for sc, rep in scored]

    finalists = []
    for sc, train_rep in scored[:max(1, int(top_k))]:
        triplets = eval_trades_triplets(sc, test, marks, notional_usd)
        test_trades_labellises = _rw.etiqueter_triplets(prep, triplets)
        test_trades = [t["net_pnl_usdc"] for t in test_trades_labellises]
        test_rep = report_from_trades(test_trades)
        gate = run_validation_gates(test_trades_labellises)
        plateau = _plateau_flag(sc, scored_map)

        # 🔴 #395 / M-19 -- LE GARDE-FOU ANTI-MULTIPLICITE, BRANCHE ICI AUSSI (2026-07-13).
        #
        # ⚠️ `evaluated` (le NOMBRE REEL de scenarios balayes : jusqu'a 150 000 000) et **surtout
        # PAS** `len(scored)` (qui n'est que la taille du TAS des meilleurs). Deflater par la
        # taille du tas au lieu du nombre d'essais rendrait le garde-fou **ridiculement
        # indulgent** -- et il aurait l'air de marcher. *Un garde-fou nourri du mauvais chiffre
        # est pire qu'un garde-fou absent : il rassure.*
        anti = _anti_overfit(test_trades, n_essais=int(evaluated))

        robust = bool(
            (train_rep["net_total_usd"] or 0.0) > 0.0
            and (test_rep["net_total_usd"] or 0.0) > 0.0
            and gate.get("verdict") == "DEPLOY_CANDIDATE"
            and plateau
            and anti.survit                       # <-- LE 5e CRITERE. Il manquait.
        )
        finalists.append({
            "scenario": _scenario_row(sc),
            "train": {kk: train_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "test": {kk: test_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "gate_verdict": gate.get("verdict"),
            "plateau": plateau,
            "anti_overfit": anti.as_dict(),
            "robust": robust,
            "regimes": _rw.repartition(test_trades_labellises),
        })

    finalists.sort(key=lambda f: (f["test"]["net_total_usd"] or 0.0), reverse=True)
    robust = [f for f in finalists if f["robust"]]
    return {
        "context": CONTEXT,
        "source": f"db:{db_path}",
        "sample": sample,
        "honesty": "streaming DB ; no-lookahead + notre notional + couts reels + train/test + voisinage (approx pool) ; aucune promesse de PnL",
        "notional_usd": notional_usd,
        "candidates_total": len(candidates),
        "train_size": len(train), "test_size": len(test), "train_frac": train_frac,
        "scenarios_evaluated": evaluated,
        "scenarios_with_min_trades": kept,
        "pool_kept": len(heap),
        "robust_count": len(robust),
        "best_robust": robust[0] if robust else None,
        "finalists": finalists,
        "note": "Fiable seulement si 'robust': net>0 train ET test ET gate ET plateau (plateau approx en streaming).",
    }


def main(argv=None):  # pragma: no cover
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Recherche massive de scenarios replay (REPLAY, paper-only)")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--max-scenarios", type=int, default=30000)
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--top-k", type=int, default=40)
    ap.add_argument("--min-trades", type=int, default=25)
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--from-db", default="",
                    help="Lit les scenarios depuis une DB SQLite (streaming, memoire bornee ; 10M-150M+)")
    ap.add_argument("--sample", type=int, default=0, help="Limite le nb de scenarios lus depuis la DB (0=tous)")
    args = ap.parse_args(argv)

    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    candidates = load_jsonl(args.candidates)
    marks = load_jsonl(args.marks)
    if args.from_db:
        report = search_over_db(candidates, marks, args.from_db,
                                sample=(args.sample or None), train_frac=args.train_frac,
                                top_k=args.top_k, min_trades=args.min_trades, jobs=jobs,
                                notional_usd=args.notional_usd)
    else:
        scenarios = generate(max_scenarios=args.max_scenarios, seed=args.seed)
        report = search(candidates, marks, scenarios, train_frac=args.train_frac,
                        top_k=args.top_k, min_trades=args.min_trades, jobs=jobs,
                        notional_usd=args.notional_usd)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"scenario_search: {report['scenarios_evaluated']} scenarios ({jobs} coeurs), "
              f"{report['robust_count']} robustes -> {args.out}")
    else:
        print(text)
    print("mode: REPLAY read-only ; aucun ordre, aucune signature, aucune promesse de PnL")
    return 0


__all__ = ["eval_trades", "report_from_trades", "temporal_split", "prefilter_candidates",
           "search", "search_over_db", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
