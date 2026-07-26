"""LABO-CONTINU-FIX — recette des 10 corrections bloquantes (Flo 26/07). Paper-only, read-only.
Couvre FX-1..FX-10 : CMD/SHA recalculés, dashboard Rich/progrès/S/Ctrl+C, outils corpus réel + Optuna,
scheduler persistant + crash + WF sans zip + LOCO/LORO même famille, forward live run-level, portefeuille
signaux promotables + sorties persistées, réconciliation cohérente, CanonicalStore par horizon + journal borné,
embargo réel, CI + recette Windows."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import pipeline_18h as PL                     # noqa: E402
import recherche_continue as RC               # noqa: E402
import canonical_store as CS                  # noqa: E402
import jobs_continue as JOBS                  # noqa: E402
import outils_recherche as OUT                # noqa: E402
import forward_portefeuille as FP             # noqa: E402
import registre_candidats_live as RCL         # noqa: E402
import progres_live as PROG                   # noqa: E402
import portefeuille_global as PG              # noqa: E402


# ═══════════════ FX-8 — CanonicalStore : exchange_ts + par horizon + journal borné + reprise ═══════════
def test_exchange_ts_prioritaire_sur_horloge_locale(tmp_path):
    st = CS.CanonicalStore(tmp_path)
    st.ingerer([{"coin": "BTC", "exchange_ts": 5000.0, "ts_wall_ms": 999999.0, "bid": 1, "ask": 2, "_source": "s"}])
    ev = list(st.etat.values())[0]
    assert ev["ts_ms"] == 5000.0 and ev["ts_source"] == "exchange_ts"       # exchange_ts prioritaire, wall en secours


def _marche(coin, ts0, ticks):
    return {coin: [{"coin": coin, "ts_ms": t, "bid": 99.9, "ask": 100.1} for t in ticks]}


def test_maturation_par_horizon_250_avant_30000(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250, 30000))
    st.ingerer([{"coin": "BTC", "ts_ms": 1000.0, "bid": 99.95, "ask": 100.05, "_source": "s"}])
    # marché couvre ts+250 (1250) mais PAS ts+30000 ; maintenant reste bien avant l'échéance de 30000
    st.maturer(_marche("BTC", 1000.0, [1250.0]), maintenant_ms=1300.0)
    prets = st.consommer()
    assert len(prets) == 1 and prets[0]["horizons"] == [250]      # 250 consommé SANS attendre 30000
    # plus tard, le futur de 30000 arrive -> il mûrit et se consomme séparément
    st.maturer(_marche("BTC", 1000.0, [31000.0]), maintenant_ms=31500.0)
    prets2 = st.consommer()
    assert len(prets2) == 1 and prets2[0]["horizons"] == [30000]


def test_journal_borne_compaction_et_reprise(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250,), snapshot_every=3)
    for i in range(5):
        st.ingerer([{"coin": "BTC", "ts_ms": float(1000 + i), "bid": 1, "ask": 2, "_source": "s%d" % i}])
    # compaction déclenchée -> snapshot écrit + journal archivé (jamais supprimé)
    assert (tmp_path / "canonical" / "snapshot.json").exists()
    assert any((tmp_path / "canonical" / "journal_archive").glob("journal_*.jsonl"))
    # REPRISE : une nouvelle instance recharge snapshot + journal -> tous les événements présents
    st2 = CS.CanonicalStore(tmp_path, horizons=(250,), snapshot_every=3)
    assert st2.compte()["n_events"] == 5 and st2.backlog() == 5


def test_reprise_crash_par_rejeu_journal(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250,), snapshot_every=9999)   # pas de compaction
    st.ingerer([{"coin": "ETH", "ts_ms": 500.0, "bid": 1, "ask": 2, "_source": "s"}])
    st2 = CS.CanonicalStore(tmp_path, horizons=(250,), snapshot_every=9999)  # "crash" -> rejeu du journal
    assert st2.backlog() == 1 and st2.compte()["n_events"] == 1


# ═══════════════ FX-9 — embargo réel ═══════════════
def test_embargo_reel_dans_walk_forward_job():
    corp = PL.corpus_fixtures()
    ctx = {"corpus": corp,
           "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h)),
           "evaluer_objets": lambda c, s, h: PL.nets_exact(c, sens=s, horizon_ms=h)}
    j = JOBS.nouveau_job("walk_forward", payload={"direction": 1, "horizon_ms": 250, "family": "GENERIC", "seuil": 8})
    JOBS.executer_job(j, contexte=ctx)
    # embargo = max(horizon, latence, features) — jamais 1 ms
    assert j["status"] in ("DONE", "BLOCKED_DATA")
    if j["status"] == "DONE":
        assert j["resultat"]["embargo_ms"] == PL.embargo_reel([250]) and j["resultat"]["embargo_ms"] > 1.0


# ═══════════════ FX-4 — file persistante + crash + signatures + WF sans zip + LOCO même famille ═══════
def test_job_queued_avant_execution_puis_terminal(tmp_path):
    store = JOBS.JobStore(tmp_path)
    j = JOBS.nouveau_job("analyse_rejets", payload={})
    store.enfiler(j)                                          # QUEUED persisté AVANT exécution
    etats = [e["status"] for e in store._stream()]
    assert etats == ["QUEUED"]


def test_running_orphelin_devient_retryable_apres_crash(tmp_path):
    store = JOBS.JobStore(tmp_path)
    j = JOBS.nouveau_job("stress_frais", payload={"direction": 1, "horizon_ms": 250})
    store.enfiler(j)
    store.enregistrer({**j, "status": "RUNNING"})            # crash : dernier état = RUNNING
    r = JOBS.JobStore(tmp_path).reprise_apres_crash()
    assert r["n_running_orphelins_retryable"] == 1
    assert JOBS.JobStore(tmp_path).dernier_par_id()[j["job_id"]]["status"] == "RETRYABLE"


def test_signatures_empechent_les_repetitions(tmp_path):
    corp = PL.corpus_fixtures()
    ctx = {"corpus": corp, "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h)),
           "evaluer_objets": lambda c, s, h: PL.nets_exact(c, sens=s, horizon_ms=h),
           "evaluer_famille": lambda c, cand: PL._nets_promo(PL.nets_exact(c, sens=cand["direction"], horizon_ms=cand["horizon_ms"]))}
    cands = [{"family": "GENERIC", "direction": 1, "horizon_ms": 250, "seuil": 8}]
    r1 = JOBS.travail_de_fond(tmp_path, ctx, candidats=cands)
    r2 = JOBS.travail_de_fond(tmp_path, ctx, candidats=cands)  # 2e passage : déterministes dédupliqués
    assert r2["n_ignores_dedupe"] > 0 and r2["aucun_idle"] is True   # revalidation/analyse tournent quand même


def test_walk_forward_sans_zip_objets_par_episode():
    corp = PL.corpus_fixtures()
    ctx = {"corpus": corp, "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h)),
           "evaluer_objets": lambda c, s, h: PL.nets_exact(c, sens=s, horizon_ms=h)}
    j = JOBS.nouveau_job("walk_forward", payload={"direction": 1, "horizon_ms": 250})
    JOBS.executer_job(j, contexte=ctx)
    assert j["status"] in ("DONE", "BLOCKED_DATA")           # aucun crash de zip de longueurs différentes


def test_loco_rejoue_la_meme_famille():
    corp = PL.corpus_fixtures()
    ctx = {"corpus": corp, "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h)),
           "evaluer_famille": lambda c, cand: PL._nets_promo(PL.nets_exact(c, sens=cand["direction"], horizon_ms=cand["horizon_ms"]))}
    j = JOBS.nouveau_job("leave_one_coin_out", payload={"family": "GENERIC", "direction": 1, "horizon_ms": 250, "seuil": 8})
    JOBS.executer_job(j, contexte=ctx)
    assert j["status"] == "DONE"
    assert j["resultat"]["rejoue_famille"] == "GENERIC" and j["resultat"]["rejoue_horizon_ms"] == 250


# ═══════════════ FX-6 — signaux promotables + cap + sorties persistées + reprise ═══════════════
def _corp_fwd(n=6, dt=100.0):
    return [{"coin": "BTC", "regime": "live", "ts_ms": float(1000 + i * 100)} for i in range(n)]


def _ev_ok(ep, *, sens, horizon_ms):
    return {"status": "OK", "promotable": True, "exit_source": "FWD_BOOK",
            "entry_ts": ep["ts_ms"], "exit_ts": ep["ts_ms"] + 100.0, "entry_px": 100.0, "exit_px": 101.0,
            "fees_bps": 1.0, "slippage_bps": 0.0, "impact_bps": 0.0, "funding_bps": 0.0, "latency_bps": 0.0}


def _ev_approx(ep, *, sens, horizon_ms):
    return {**_ev_ok(ep, sens=sens, horizon_ms=horizon_ms), "promotable": False, "exit_source": "FWD_MID_PLUS_SPREAD"}


def test_signaux_exigent_promotable_et_fwd_book():
    geles = [{"trial_id": "c1", "coin": "BTC", "regime": "live", "direction": 1, "horizon_ms": 250}]
    fil = lambda corp, coin=None, regime=None: corp
    ok = FP._signaux(geles, _corp_fwd(), filtrer=fil, evaluer=_ev_ok)
    approx = FP._signaux(geles, _corp_fwd(), filtrer=fil, evaluer=_ev_approx)
    assert len(ok) > 0 and len(approx) == 0                  # APPROXIMATE jamais tradé


def test_cap_par_candidat_configurable():
    geles = [{"trial_id": "c1", "coin": "BTC", "regime": "live", "direction": 1, "horizon_ms": 250}]
    fil = lambda corp, coin=None, regime=None: corp
    assert len(FP._signaux(geles, _corp_fwd(8), filtrer=fil, evaluer=_ev_ok, max_par_candidat=2)) == 2
    assert len(FP._signaux(geles, _corp_fwd(8), filtrer=fil, evaluer=_ev_ok, max_par_candidat=None)) == 8


class _PFStub:
    def __init__(self):
        self.ouvertes, self.fermees = {}, []
    def ouvrir(self, pid, **kw):
        self.ouvertes[pid] = kw
        return {}
    def fermer(self, pid, *, prix, ts_ms, couts=None):
        self.fermees.append(pid)
        self.ouvertes.pop(pid, None)
        return {}
    def reconcilier(self):
        return {"coherent": True}


def test_sorties_persistees_et_reprise_sans_fermeture_manuelle(tmp_path):
    geles = [{"trial_id": "c1", "coin": "BTC", "regime": "live", "direction": 1, "horizon_ms": 250}]
    fil = lambda corp, coin=None, regime=None: corp
    pend = tmp_path / "pending.json"
    pf1 = _PFStub()
    # maintenant AVANT la dernière échéance -> au moins une position reste OUVERTE et sa sortie est PERSISTÉE
    # (les positions dont l'échéance tombe avant une entrée ULTÉRIEURE mûrissent naturellement — c'est correct ;
    #  ce qu'on interdit, c'est de TOUT fermer en fin de passe alors que l'échéance n'est pas arrivée).
    r1 = FP.simuler(geles, _corp_fwd(4), filtrer=fil, evaluer=_ev_ok, portefeuille=pf1,
                    pending_path=pend, maintenant_ms=900.0)
    assert r1["n_sorties_en_attente"] >= 1 and pend.exists()
    assert len(json.loads(pend.read_text(encoding="utf-8"))) >= 1     # sortie non mûre persistée sur disque
    # "reprise" : nouvelle simulation, capital neuf, MÊME fichier pending, maintenant très avancé -> fermeture AUTO
    pf2 = _PFStub()
    FP.simuler([], _corp_fwd(0), filtrer=fil, evaluer=_ev_ok, portefeuille=pf2,
               pending_path=pend, maintenant_ms=10 ** 9)
    assert len(pf2.fermees) > 0                              # fermées automatiquement, aucun test ne ferme à la main


# ═══════════════ FX-7 — réconciliation cohérente (streaming) ═══════════════
def test_portefeuille_global_reconcilie_en_streaming(tmp_path):
    pf = PG.PortefeuilleGlobal(tmp_path / "gp", capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, ts_ms=1.0,
              couts={"fees_bps": 2.0})
    pf.fermer("p1", prix=101.0, ts_ms=2.0, couts={"fees_bps": 2.0})
    rc = pf.reconcilier()
    assert rc["coherent"] is True and abs(rc["cash_ledger"] - rc["cash_snapshot"]) < 1e-6


def test_reconciliation_coherent_calcule_pas_code(tmp_path):
    # portefeuille global cohérent -> _coherence_reconciliation renvoie True calculé
    pf = PG.PortefeuilleGlobal(tmp_path / "global_portfolio", capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, ts_ms=1.0)
    pf.fermer("p1", prix=101.0, ts_ms=2.0)
    import reconciliation_prod as RECO
    glob = RECO.reconstruire_global([tmp_path / "global_portfolio" / "ledger.jsonl"])
    coherent, detail = RC._coherence_reconciliation(tmp_path, glob)
    assert coherent is True and detail["verifie"] is True
    # sans portefeuille global : coherent=None (rien à vérifier, honnête) — jamais True fabriqué
    c2, d2 = RC._coherence_reconciliation(tmp_path / "vide", glob)
    assert c2 is None


# ═══════════════ FX-5 — registre run-level des candidats figés ═══════════════
def test_admissible_strictement_apres_freeze():
    eps = [{"coin": "BTC", "ts_ms": 900.0}, {"coin": "BTC", "ts_ms": 1000.0}, {"coin": "BTC", "ts_ms": 1200.0}]
    adm = RCL.filtrer_apres_freeze(eps, 1000.0)
    assert [e["ts_ms"] for e in adm] == [1200.0]             # strictement > freeze (900 et 1000 exclus)


def test_registre_fige_immuable_et_suivi_continu(tmp_path):
    reg = RCL.RegistreCandidatsLive(tmp_path)
    reg.figer("c1", freeze_exchange_ts=1000.0, meta={"direction": 1, "horizon_ms": 250, "coin": "BTC"})
    reg.figer("c1", freeze_exchange_ts=5000.0)               # re-figer NE change pas le freeze
    assert reg.etat["c1"]["freeze_exchange_ts"] == 1000.0
    reg.suivre("c1", nets_live=[10.0, -3.0, 5.0], last_event_id="e9", maintenant_ms=2000.0)
    # "redémarrage" : nouvelle instance -> le candidat et son suivi persistent
    reg2 = RCL.RegistreCandidatsLive(tmp_path)
    c = reg2.etat["c1"]
    assert c["n_episodes_live"] == 3 and c["positif_live"] is True and c["last_forward_event_id"] == "e9"


# ═══════════════ FX-3 — outils : corpus réel + Optuna honnête + samplers/pruners/NSGA ═══════════════
def test_outils_disponibilite_honnete_et_roles():
    d = OUT.disponibilite()
    assert d["grid"]["disponible"] and d["random"]["disponible"] and d["qmc"]["disponible"]
    # samplers/pruners avancés : disponibles SEULEMENT si optuna présent (sinon False honnête)
    import importlib
    a_optuna = importlib.util.find_spec("optuna") is not None
    for o in ("tpe", "cma_es", "nsga2", "successive_halving", "hyperband"):
        assert d[o]["disponible"] is a_optuna
    assert OUT.PRUNERS_OPTUNA["hyperband"] == "HyperbandPruner"
    assert OUT.SAMPLERS_OPTUNA["nsga2"] == "NSGAIISampler" and "nsga2" in OUT.MULTI_OBJECTIF


def test_outils_purs_produisent_de_vrais_trials():
    def _eval(p):
        return {"net_median_bps": 5.0 - abs(p.get("x", 0)), "pf": 1.2, "n": 10}
    reg = OUT.lancer_registre(_eval, {"x": [0, 1, 2]}, n_trials=6)
    assert reg["n_avec_trials_reels"] >= 3                   # grid/random/qmc tournent réellement


# ═══════════════ FX-2 — progression live + dashboard ═══════════════
def test_progres_live_calcule_pourcentage_et_vitesse():
    PROG.reset(10, job="phase X", ensuite="phase Y")
    PROG.publier(5)
    time.sleep(0.01)
    r = PROG.lire()
    assert r["total"] == 10 and r["fait"] == 5 and r["pourcentage"] == 50.0 and r["job"] == "phase X"


def test_dashboard_rendre_rich_disponible():
    import dashboard_flow as DF
    r = DF.rendre_rich({"totaux": {}})
    assert r is not None                                     # Rich renderable ou repli texte, jamais None


# ═══════════════ FX-2 + FX-5 wiring : un run borné remplit progression + ctrl_c réels ═══════════════
def test_run_borne_remplit_progression_et_ctrl_c(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"
    d.mkdir(parents=True)
    lignes = [{"venue": "HL", "coin": "BTC", "ts_wall_ms": 1_000_000 + i * 1000,
               "bid": 64000 * (1 + i * 0.003), "ask": 64000 * (1 + i * 0.003) + 1, "isSnapshot": False}
              for i in range(60)]
    (d / "bbo.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    etat = json.loads((tmp_path / "runtime" / "research_lab" / "continuous").glob("rcont-*").__next__()
                      .joinpath("LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
    cj = etat["ce_que_je_fais"]
    assert cj["total"] is not None and cj["pourcentage"] is not None       # progression jamais None (FX-2)
    assert "candidats suivis" in etat["ctrl_c"]["termine"]                  # conseil Ctrl+C basé sur des signaux réels


# ═══════════════ FX-1 — CMD/SHA recalculés + capture run_id ═══════════════
def test_verifier_manifeste_recalcule_les_sha(tmp_path):
    rundir = tmp_path / "rcont-x"
    (rundir / "manifeste").mkdir(parents=True)
    f = rundir / "results.txt"
    f.write_text("donnee", encoding="utf-8")
    man = rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json"
    man.write_text(json.dumps({"fichiers": {"results.txt": RC._sha(f)}, "code_sha": "z"}), encoding="utf-8")
    assert RC._verifier_manifeste_sha(man, rundir)["ok"] is True
    f.write_text("ALTERE", encoding="utf-8")                 # falsification -> SHA divergent détecté
    v = RC._verifier_manifeste_sha(man, rundir)
    assert v["ok"] is False and v["n_diverge"] == 1


def test_capture_dernier_run_lance(tmp_path):
    RC._ecrire_dernier_run_lance(tmp_path, "rcont-abc123")
    assert RC._lire_dernier_run_lance(tmp_path) == "rcont-abc123"


# ═══════════════ GR-1 — suivi live CUMULATIF (dédup id, cumul multi-cycles, cycle vide sans reset) ═══════
def test_suivi_live_cumule_et_deduplique(tmp_path):
    reg = RCL.RegistreCandidatsLive(tmp_path)
    reg.figer("c1", freeze_exchange_ts=1.0)                  # freeze > 0 (0 est désormais interdit)
    reg.suivre("c1", paires=[("e1", 10.0), ("e2", -4.0)])
    reg.suivre("c1", paires=[("e2", -4.0), ("e3", 6.0)])     # e2 DÉJÀ vu -> dédup par episode_id
    c = reg.etat["c1"]
    assert c["n_episodes_live"] == 3 and c["pnl_live_bps"] == 12.0   # cumul 10-4+6 ; e2 non recompté
    assert c["dd_live_bps"] >= 0.0 and c["last_forward_event_id"] == "e3"
    reg.suivre("c1", paires=[], maintenant_ms=100.0)         # cycle VIDE -> AUCUN reset
    c2 = reg.etat["c1"]
    assert c2["n_episodes_live"] == 3 and c2["pnl_live_bps"] == 12.0 and c2["duree_live_ms"] == 99.0  # 100 - freeze(1)


def test_suivi_live_cumul_survit_aux_cycles(tmp_path):
    RCL.RegistreCandidatsLive(tmp_path).figer("c1", freeze_exchange_ts=1.0)
    RCL.RegistreCandidatsLive(tmp_path).suivre("c1", paires=[("a", 5.0)])   # nouvelle instance = nouveau cycle
    RCL.RegistreCandidatsLive(tmp_path).suivre("c1", paires=[("b", 5.0)])
    assert RCL.RegistreCandidatsLive(tmp_path).etat["c1"]["n_episodes_live"] == 2   # cumul persistant


# ═══════════════ GR-2 — pré-forward diagnostic n'alimente PAS le global ═══════════════
def test_pre_forward_ne_nourrit_pas_le_portefeuille_global(tmp_path):
    rd = tmp_path / "rd"
    PL.executer_pipeline_complet(tmp_path, rd, PL.corpus_fixtures(), code_sha="gr2",
                                 portefeuille_global_dir=(rd / "global_portfolio"))
    # le PRÉ-FORWARD (archive) ne crée JAMAIS le ledger du portefeuille global
    assert not (rd / "global_portfolio" / "ledger.jsonl").exists()
    r = json.loads((rd / "resultats" / "forward_portfolio_reconciliation.json").read_text(encoding="utf-8"))
    assert r.get("alimente_global") is False and r.get("pre_forward_diagnostic") is True


# ═══════════════ GR-4 — Hyperband/SuccessiveHalving : ressource RÉELLEMENT croissante ═══════════════
def test_ladder_ressource_strictement_croissante():
    assert list(OUT.RESSOURCE_LADDER) == sorted(OUT.RESSOURCE_LADDER) and len(set(OUT.RESSOURCE_LADDER)) >= 4


def test_hyperband_utilise_ressource_croissante_reelle():
    import importlib
    if importlib.util.find_spec("optuna") is None:
        import pytest
        pytest.skip("optuna absent — samplers/pruners avancés indisponibles (honnête)")
    budgets_vus = []
    def _eval(params, budget=1.0):
        budgets_vus.append(round(float(budget), 3))
        return {"net_median_bps": 5.0 * budget, "pf": 1.1, "n": int(100 * budget)}
    r = OUT.optimiser(_eval, {"x": [0, 1, 2]}, outil="hyperband", n_trials=4)
    assert r["disponible"] and r["lance"] and r["pruner"] == "HyperbandPruner"
    assert r.get("ressource_croissante") == list(OUT.RESSOURCE_LADDER)
    assert 0.2 in budgets_vus and max(budgets_vus) > min(budgets_vus)      # étapes à budget CROISSANT
    assert len(set(budgets_vus)) >= 2                                       # pas 4x exactement le même calcul


def test_successive_halving_disponible_avec_optuna():
    import importlib
    if importlib.util.find_spec("optuna") is None:
        import pytest
        pytest.skip("optuna absent")
    r = OUT.optimiser(lambda p, budget=1.0: {"net_median_bps": 3.0, "pf": 1.0, "n": 10},
                      {"x": [0, 1]}, outil="successive_halving", n_trials=3)
    assert r["disponible"] and r["pruner"] == "SuccessiveHalvingPruner" and r.get("ressource_croissante")


# ═══════════════ GR-3 — CMD durci : effacement du pointeur de run ═══════════════
def test_effacer_dernier_run_lance(tmp_path):
    RC._ecrire_dernier_run_lance(tmp_path, "rcont-x")
    assert RC._lire_dernier_run_lance(tmp_path) == "rcont-x"
    RC._effacer_dernier_run_lance(tmp_path)
    assert RC._lire_dernier_run_lance(tmp_path) == ""        # effacé -> le CMD ne vérifiera jamais un ancien run


# ═══════════════ MICRO-FIX point 1 — jamais de gel à 0 (e2e) ═══════════════
def test_e2e_jamais_de_gel_a_zero_sans_horloge_live(tmp_path):
    import champions_continue as CH
    CH.enregistrer_candidat(tmp_path, {"trial_id": "c1", "direction": 1, "horizon_ms": 250, "coin": "BTC",
                                       "family": "GENERIC"})
    # AUCUNE horloge live (pas de prets, pas de buffer marché) -> le champion N'EST PAS gelé, il ATTEND
    RC._suivi_candidats_live(tmp_path, [])
    reg = RCL.RegistreCandidatsLive(tmp_path)
    assert reg.etat == {}                                    # aucun candidat gelé (jamais freeze=0)
    assert any(v.get("statut") == "WAITING_FOR_LIVE_CLOCK" for v in reg.attente.values())
    # une horloge live arrive via le buffer marché du CanonicalStore -> gel au VRAI exchange_ts (> 0)
    (tmp_path / "canonical").mkdir(parents=True, exist_ok=True)
    (tmp_path / "canonical" / "marche.jsonl").write_text(
        json.dumps({"coin": "BTC", "ts_ms": 123456.0, "bid": 1, "ask": 2}) + "\n", encoding="utf-8")
    RC._suivi_candidats_live(tmp_path, [])
    reg2 = RCL.RegistreCandidatsLive(tmp_path)
    assert reg2.etat and reg2.etat["c1"]["freeze_exchange_ts"] == 123456.0   # gel au dernier ts observé, jamais 0


# ═══════════════ MICRO-FIX point 2 — PASS_FORWARD_PAPER exige une preuve LIVE (e2e) ═══════════════
def test_e2e_pass_forward_paper_exige_preuve_live(tmp_path):
    # 1) le pipeline sur ARCHIVE seule ne produit JAMAIS PASS_FORWARD_PAPER (au mieux PASS_PRE_FORWARD)
    rd = tmp_path / "rd"
    PL.executer_pipeline_complet(tmp_path, rd, PL.corpus_fixtures(), code_sha="p2")
    finals = json.loads((rd / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
    assert all(f.get("verdict") != "PASS_FORWARD_PAPER" for f in finals)    # pré-forward ne passe jamais en direct
    # 2) promotion : SANS preuve live -> refus ; AVEC (registre >=MIN + global cohérent) -> PASS_FORWARD_PAPER
    camp = tmp_path / "camp"
    (camp / "resultats").mkdir(parents=True)
    (camp / "resultats" / "final_verdicts.json").write_text(
        json.dumps([{"trial_id": "c1", "verdict": "PASS_PRE_FORWARD"}]), encoding="utf-8")
    assert RC._promouvoir_pass_live(tmp_path, camp)["n_pass_live"] == 0     # aucune donnée live -> pas de promotion
    reg = RCL.RegistreCandidatsLive(tmp_path)
    reg.figer("c1", freeze_exchange_ts=1000.0)
    reg.suivre("c1", paires=[("e%d" % i, 1.0) for i in range(RC.MIN_LIVE_EPISODES_POUR_PASS)])   # >= minimum réel
    pf = PG.PortefeuilleGlobal(tmp_path / "global_portfolio")               # portefeuille GLOBAL live réconciliable
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, ts_ms=1.0)
    pf.fermer("p1", prix=101.0, ts_ms=2.0)
    r1 = RC._promouvoir_pass_live(tmp_path, camp)
    assert r1["n_pass_live"] == 1 and r1["global_reconcilie"] is True
    f2 = json.loads((camp / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))[0]
    assert f2["verdict"] == "PASS_FORWARD_PAPER" and f2["live_confirme"] is True
    assert f2["n_episodes_live"] >= RC.MIN_LIVE_EPISODES_POUR_PASS and "pnl_live_bps" in f2


# ═══════════════ FX-10 — CI + recette Windows livrées ═══════════════
def test_livrables_ci_et_recette_presents():
    assert (RACINE / ".github" / "workflows" / "labo-continu-ci.yml").exists()
    assert (RACINE / "RECETTE-WINDOWS.cmd").exists()
    assert (RACINE / "requirements-recherche.txt").exists()
    txt = (RACINE / "requirements-recherche.txt").read_text(encoding="utf-8")
    assert "optuna" in txt and "cmaes" in txt
    import importlib
    assert importlib.util.find_spec("recette_windows_smoke") is not None   # backbone importable
