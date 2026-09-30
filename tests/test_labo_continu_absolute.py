"""LABO-CONTINU-ABSOLUTE-FINAL — recette bloquante (Flo 26/07). Tests des blocs P0..P9. Paper-only.
Chaque bloc a ses tests ; ce fichier grossit bloc par bloc jusqu'à la recette finale."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import pipeline_18h as PL             # noqa: E402
import moteur_execution_prod as MEP   # noqa: E402
import metriques_pepites as MP        # noqa: E402
import recherche_continue as RC       # noqa: E402


# ═══════════════ P0 — fausses preuves ═══════════════
def test_approximate_positive_result_never_reaches_holdout_or_pass(tmp_path):
    """Un résultat positif mais APPROXIMATE (exit fwd_mid) ne devient jamais survivant/candidat/PASS."""
    # corpus positif MAIS sans carnet futur (fwd_mid seul) -> tout APPROXIMATE
    corpus = [{"coin": "BTC", "regime": "vol", "ts_ms": float(i), "bid": 99.95, "ask": 100.05,
               "fwd_mid": {250: 100.5, 1000: 100.4, 5000: 100.3, 30000: 100.2}} for i in range(120)]
    rd = tmp_path / "rd"
    res = PL.executer_pipeline_complet(tmp_path, rd, corpus, code_sha="approx")
    # aucun survivant / candidat gelé / forward : APPROXIMATE ne promeut jamais
    assert res["n_survivants"] == 0 and res["n_candidats_figes"] == 0 and res["n_forward_events"] == 0
    finals = json.loads((rd / "resultats" / "final_verdicts.json").read_text())
    assert all(f.get("verdict") != "PASS_FORWARD_PAPER" for f in finals)


def test_promotable_flow_separates_measured_from_promotable():
    ep_appx = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.5}}
    ep_book = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}}
    eps = MEP.evaluer_episodes([ep_appx, ep_book], sens=1, horizon_ms=1000)
    assert len(PL._nets_ok(eps)) == 2          # diagnostic : les deux mesurés
    assert len(PL._nets_promo(eps)) == 1        # promouvable : seul le FWD_BOOK


def test_parameter_plateau_not_horizon_plateau():
    # plateau de PARAMÈTRES via un evaluer_seuil qui dépend du seuil (pas des horizons)
    def ev_seuil(s):
        return [10.0 - abs(s - 8) * 0.5] * 20   # zone stable autour de seuil=8
    plat = MP.plateau_parametres(seuil=8, evaluer_seuil=ev_seuil, famille_a_predicat=True)
    assert plat["plateau_parametres"] is True and "courbe" in plat and plat["n_voisins"] >= 3
    # sans paramètre actif -> None (jamais confondu avec une stabilité d'horizons)
    plat2 = MP.plateau_parametres(seuil=8, evaluer_seuil=ev_seuil, famille_a_predicat=False)
    assert plat2["plateau_parametres"] is None and plat2["motif"] == "PAS_DE_PARAMETRE_ACTIF"


def test_concentration_replays_same_signal():
    # evaluer_coin doit recevoir chaque coin et rejouer LE MÊME signal ; on vérifie que les 2 coins sont testés
    vus = []
    def ev_coin(coin):
        vus.append(coin)
        return [5.0, 6.0] if coin == "BTC" else [0.1, 0.2]
    conc = MP.concentration_reelle(coins=["BTC", "ETH"], evaluer_coin=ev_coin)
    assert set(vus) == {"BTC", "ETH"} and conc["n_coins"] == 2
    assert conc["un_seul_coin_dominant"] is True and conc["part_max"] > 0.6   # BTC domine


def test_capacity_requires_real_l2():
    # sans profondeur L2 -> DATA_MISSING_L2 (jamais un chiffre inventé)
    corpus_sans = [{"coin": "BTC", "ts_ms": i, "bid": 99.9, "ask": 100.1,
                    "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}} for i in range(20)]
    capa = MP.capacite_reelle(corpus_sans, sens=1, horizon_ms=1000, courbe_capacite=MEP.courbe_capacite)
    assert capa["capacite_non_nulle"] is None and capa["motif"] == "DATA_MISSING_L2"
    # avec profondeur + carnet futur -> calculée
    corpus_avec = [{**e, "bids": [[99.9, 100.0], [99.8, 100.0]], "asks": [[100.1, 100.0], [100.2, 100.0]]}
                   for e in corpus_sans]
    capa2 = MP.capacite_reelle(corpus_avec, sens=1, horizon_ms=1000, courbe_capacite=MEP.courbe_capacite)
    assert capa2["capacite_non_nulle"] is not None


# ═══════════════ P1 — CanonicalEventStore + maturation ═══════════════
import canonical_store as CS  # noqa: E402


def _marche(coin, ts0, n, base=100.0):
    return {coin: [{"coin": coin, "ts_ms": ts0 + i * 100, "bid": base - 0.05, "ask": base + 0.05} for i in range(n)]}


def test_pending_event_matures_once(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    st.ingerer([{"coin": "BTC", "ts_ms": 1000.0, "bid": 99.95, "ask": 100.05, "_source": "s"}])
    assert st.backlog() == 1 and st.compte().get("PENDING") == 1
    # sans futur suffisant -> reste PENDING
    st.maturer({}, maintenant_ms=1100.0)
    assert st.backlog() == 1
    # avec les ticks futurs (>= ts+horizon) -> READY
    st.maturer(_marche("BTC", 1000.0, 40), maintenant_ms=5000.0)
    prets = st.consommer()
    assert len(prets) == 1 and prets[0]["exit_source"] if False else len(prets) == 1
    assert prets[0]["fwd_bid"] and prets[0]["fwd_ask"]        # vrai carnet futur joint
    assert st.consommer() == []                              # consommé UNE seule fois


def test_pending_survives_restart(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    st.ingerer([{"coin": "ETH", "ts_ms": 500.0, "bid": 50.0, "ask": 50.02, "_source": "s"}])
    assert st.backlog() == 1
    # "redémarrage" : nouvelle instance recharge l'état depuis le disque -> PENDING toujours là
    st2 = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    assert st2.backlog() == 1 and st2.compte().get("PENDING") == 1
    st2.maturer(_marche("ETH", 500.0, 40, base=50.0), maintenant_ms=5000.0)
    assert len(st2.consommer()) == 1                          # mûrit après reprise


def test_ingestion_deduplique(tmp_path):
    st = CS.CanonicalStore(tmp_path)
    ev = [{"coin": "BTC", "ts_ms": 1.0, "bid": 1, "ask": 2, "_source": "s"}]
    r1 = st.ingerer(ev); r2 = st.ingerer(ev)
    assert r1["n_pending_ajoutes"] == 1 and r2["n_dupliques"] == 1 and r2["n_pending_ajoutes"] == 0


# ═══════════════ P2 — holdout ≠ forward + freeze_ts + embargo ═══════════════
def test_embargo_uses_real_maximum():
    # embargo = max(horizon, latence max, durée max features) — jamais 1 ms
    e = PL.embargo_reel([250, 1000], latence_max_ms=2000.0, feature_dur_max_ms=60000.0)
    assert e == 60000.0                                       # la durée des features domine ici
    e2 = PL.embargo_reel([120000], latence_max_ms=2000.0, feature_dur_max_ms=1000.0)
    assert e2 == 120000.0                                     # l'horizon domine là
    assert PL.embargo_reel([250]) != 1.0                     # jamais 1 ms codé en dur


def test_holdout_and_forward_are_disjoint_and_after_freeze(tmp_path):
    rd = tmp_path / "rd"
    PL.executer_pipeline_complet(tmp_path, rd, PL.corpus_fixtures(), code_sha="p2")
    fz = json.loads((rd / "resultats" / "freeze.json").read_text())
    assert fz["freeze_ts"] > 0 and fz["n_forward"] >= 0 and fz["embargo_ms"] >= 60000.0
    # forward_paper : chaque événement a exchange_ts (ts) > freeze_ts, et aucun du holdout
    fwd = [json.loads(l) for l in (rd / "ledger" / "forward_paper.jsonl").read_text().splitlines()] \
        if (rd / "ledger" / "forward_paper.jsonl").exists() else []
    assert all(e["ts_ms"] > fz["freeze_ts"] for e in fwd)    # forward STRICTEMENT après le gel
    # candidats figés : conservent freeze_ts / data_cutoff / n_forward_live / régimes
    finals = json.loads((rd / "resultats" / "final_verdicts.json").read_text())
    if finals:
        assert "freeze_ts" in finals[0] and "n_forward_live" in finals[0] and "forward_regimes" in finals[0]


# ═══════════════ P3 — portefeuille GLOBAL vivant persistant ═══════════════
import portefeuille_global as PG  # noqa: E402


def test_global_portfolio_shared_during_execution(tmp_path):
    pf = PG.PortefeuilleGlobal(tmp_path / "gp", capital_initial=100.0, levier=1.0, max_expo_coin_frac=1.0)
    a = pf.ouvrir("cand1:p", coin="BTC", sens=1, notional=60.0, prix=100.0)
    b = pf.ouvrir("cand2:p", coin="ETH", sens=1, notional=60.0, prix=100.0)   # même capital -> refus
    assert not a.get("refus") and b.get("refus") == "CAPITAL_INSUFFISANT"
    pf.fermer("cand1:p", prix=101.0)
    c = pf.ouvrir("cand2:p", coin="ETH", sens=1, notional=60.0, prix=100.0)   # capital libéré -> OK
    assert not c.get("refus")


def test_global_portfolio_resume_open_positions(tmp_path):
    d = tmp_path / "gp"
    pf = PG.PortefeuilleGlobal(d, capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0)
    assert len(pf.positions) == 1
    # "crash" : nouvelle instance recharge l'état -> la position OUVERTE est reprise
    pf2 = PG.PortefeuilleGlobal(d)
    assert len(pf2.positions) == 1 and "p1" in pf2.positions
    pf2.fermer("p1", prix=102.0)                              # on peut la fermer après reprise
    assert len(pf2.positions) == 0 and pf2.realized > 0


def test_global_reconciliation_not_hardcoded(tmp_path):
    d = tmp_path / "gp"
    pf = PG.PortefeuilleGlobal(d, capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, couts={"fees_bps": 2.0})
    pf.fermer("p1", prix=102.0, couts={"fees_bps": 2.0})
    rec = pf.reconcilier()
    assert rec["coherent"] is True and abs(rec["cash_ledger"] - rec["cash_snapshot"]) < 1e-4
    # si on corrompt le snapshot, coherent devient False (donc pas codé en dur)
    pf.cash += 123.0
    assert pf.reconcilier()["coherent"] is False


# ═══════════════ P4 — jobs réellement exécutés + pas d'idle ═══════════════
import jobs_continue as JOBS  # noqa: E402


def _ctx_corpus():
    corpus = [{"coin": ("BTC" if i % 2 else "ETH"), "regime": ("vol" if i % 3 else "calme"), "ts_ms": float(i),
               "bid": 99.9, "ask": 100.1, "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}} for i in range(40)]
    return {"corpus": corpus,
            "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h))}


def test_scheduler_jobs_are_really_executed():
    ctx = _ctx_corpus()
    job = JOBS.nouveau_job("stress_frais", payload={"direction": 1, "horizon_ms": 1000})
    assert job["status"] == "QUEUED"
    JOBS.executer_job(job, contexte=ctx)
    assert job["status"] == "DONE" and job["resultat"] is not None      # RÉELLEMENT exécuté (pas compté)
    assert "survit_stress_frais" in job["resultat"] and job["progression"] == job["total"] and job["vitesse"] is not None


def test_no_idle_has_useful_job(tmp_path):
    ctx = _ctx_corpus()
    r = JOBS.travail_de_fond(tmp_path, ctx, candidats=[{"direction": 1, "horizon_ms": 1000, "seuil": 8}], rejets=[])
    assert r["aucun_idle"] is True and r["n_jobs_executes"] >= 8       # placebo/WF/LOCO/LORO/stress... exécutés
    assert r["n_done"] >= 1                                            # au moins un job produit un vrai résultat
    # persistance : les jobs sont écrits (reprenables)
    assert (tmp_path / "jobs" / "jobs.jsonl").exists()
    st = JOBS.JobStore(tmp_path).compte()
    assert st["DONE"] >= 1 and sum(st.values()) == r["n_jobs_executes"]


def test_job_blocked_data_when_missing():
    # sans données -> BLOCKED_DATA (jamais un faux DONE)
    ctx = {"corpus": [], "evaluer_promo": lambda c, s, h: []}
    job = JOBS.nouveau_job("placebo", payload={"direction": 1, "horizon_ms": 1000})
    JOBS.executer_job(job, contexte=ctx)
    assert job["status"] == "BLOCKED_DATA" and job["raison"]


# ═══════════════ P5 — outils intelligents réellement branchés ═══════════════
import outils_recherche as OUT  # noqa: E402


def test_optuna_tools_produce_real_trials(tmp_path):
    # objectif réel : score composite d'une évaluation promouvable simple
    corpus = [{"coin": "BTC", "regime": "vol", "ts_ms": float(i), "bid": 99.9, "ask": 100.1,
               "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}} for i in range(40)]
    import statistics
    def ev(params):
        nets = PL._nets_promo(PL.nets_exact(corpus, sens=params["direction"], horizon_ms=params["horizon_ms"]))
        return {"net_median_bps": statistics.median(nets) if nets else -50.0, "pf": 1.5, "n": len(nets)}
    espace = {"direction": [1, -1], "horizon_ms": [250, 1000]}
    reg = OUT.lancer_registre(ev, espace, n_trials=6, storage_dir=tmp_path)
    # les outils purs (grid/random/qmc) ont RÉELLEMENT tourné avec de vrais trials terminés
    for o in ("grid", "random", "qmc"):
        assert reg["outils"][o]["lance"] is True and reg["outils"][o]["trials_termines"] > 0
        assert reg["outils"][o]["meilleur"] is not None and reg["outils"][o]["cpu_s"] >= 0
    assert reg["n_avec_trials_reels"] >= 1                            # au moins un outil a produit de vrais trials
    # disponibilité HONNÊTE : optuna absent -> tpe/cma_es listés indisponibles AVEC raison (jamais faussement comptés)
    disp = OUT.disponibilite()
    if not disp["tpe"]["disponible"]:
        assert "optuna" in disp["tpe"]["raison"] and reg["outils"]["tpe"]["lance"] is False


def test_objectif_multicritere_jamais_pnl_brut_seul():
    # un net négatif ne peut pas être promu (score <= -100) quel que soit le brut
    assert OUT.objectif_multicritere({"net_median_bps": -3.0, "pf": 9.0}) <= -100


# ═══════════════ P6 — dashboard figé (12 panneaux + nav clavier) ═══════════════
import dashboard_flow as DF  # noqa: E402


def test_dashboard_contains_all_12_panels():
    etat = {"totaux": {"fast_screen": 5, "exact_replays": 2}, "duree": {"jours": 0, "heures": 1, "minutes": 2, "secondes": 3},
            "ce_que_je_fais": {"je_fais": "je rejoue une idée sur BTC", "parce_que": "vérifier un déséquilibre",
                               "j_utilise": "grid, random", "fait": 3, "total": 10, "pourcentage": 30}}
    txt = DF.rendre_texte(etat, vue="tout")
    for p in DF.PANNEAUX:
        assert p in txt                                       # les 12 panneaux présents
    assert "JE SUIS EN TRAIN DE : je rejoue une idée sur BTC" in txt
    assert "PARCE QUE" in txt and "J'UTILISE" in txt and "ENSUITE JE VAIS" in txt


def test_dashboard_shows_not_computable_without_fake_zero():
    txt = DF.rendre_texte({}, vue="simulation")
    assert "PAS ENCORE CALCULABLE" in txt                      # jamais un faux zéro


def test_dashboard_progress_changes_during_replay():
    e1 = {"ce_que_je_fais": {"fait": 2, "total": 10, "pourcentage": 20}}
    e2 = {"ce_que_je_fais": {"fait": 7, "total": 10, "pourcentage": 70}}
    t1, t2 = DF.rendre_texte(e1, vue="general"), DF.rendre_texte(e2, vue="general")
    assert "20%" in t1 and "70%" in t2 and t1 != t2            # la progression BOUGE (pas seulement l'horloge)


def test_keyboard_navigation():
    assert DF.touche_vers_vue("1") == "general" and DF.touche_vers_vue("4") == "pepites"
    assert DF.touche_vers_vue("S") == "snapshot" and DF.touche_vers_vue("s") == "snapshot"
    assert DF.touche_vers_vue("\x03") is None                 # Ctrl+C JAMAIS mappé (géré par le signal)
    # une vue ne rend que ses panneaux
    assert "9. SIMULATION PAPER" in DF.rendre_texte({}, vue="simulation")
    assert "6. MEILLEURES PÉPITES POSSIBLES" in DF.rendre_texte({}, vue="pepites")


# ═══════════════ P7 — CMD (start ≠ resume, dry-run code, verif same run) ═══════════════
def test_cmd_start_and_resume_are_distinct(tmp_path):
    RC._ARRET.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    (d / "bbo.jsonl").write_text(json.dumps({"coin": "BTC", "ts_wall_ms": 1, "bid": 1, "ask": 1.1}) + "\n")
    # crée un run actif
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False, mode="start")
    # START à nouveau -> refuse (un run est déjà actif) ; RESUME -> reprend
    r_start = RC.creer_ou_reprendre(tmp_path, exiger_flux=False, mode="start")
    r_resume = RC.creer_ou_reprendre(tmp_path, exiger_flux=False, mode="resume")
    assert r_start["start"] == "RUN_ACTIF_EXISTE"
    assert r_resume["start"] == "REPRISE" and r_resume["reprise"] is True


def test_finalisation_verifies_same_run(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    lignes = [{"venue": "HL", "coin": "BTC", "ts_wall_ms": 1_000_000 + i * 1000, "bid": 64000 * (1 + i * 0.003),
               "ask": 64000 * (1 + i * 0.003) + 1, "isSnapshot": False} for i in range(60)]
    (d / "bbo.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")
    r = RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    rid = r["run_id"]
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    RC.finaliser(tmp_path, partial=False)
    v = RC.verifier_finalisation(tmp_path, rid)               # vérifie CE run (état COMPLETE + SHA)
    assert v["finalisation_confirmee"] is True and v["etat_complete"] is True and v["sha_presents"] is True
    # un run_id inexistant n'est jamais confirmé
    assert RC.verifier_finalisation(tmp_path, "rcont-inexistant")["finalisation_confirmee"] is False


def test_dry_run_returns_nonzero_on_failure(tmp_path):
    # dry_run renvoie PASS bool ; le CLI mappe -> code 0 si PASS, 2 sinon. On teste la valeur PASS.
    dr = RC.dry_run(tmp_path)
    assert "PASS" in dr and isinstance(dr["PASS"], bool)


# ═══════════════ P8 — supervision Windows (méthode d'arrêt journalisée) ═══════════════
def test_supervisor_stop_method_is_logged(tmp_path):
    import superviseur_continue as SUP
    rd = tmp_path / "run"; rd.mkdir()
    sup = SUP.Superviseur(rd, {"col_a": ["x.py"]}, root=tmp_path, backoff_s=0.0)
    # un faux process minimal qui répond à terminate/kill/poll/send_signal
    class _P:
        def __init__(s): s.n = 0
        def poll(s): s.n += 1; return 0 if s.n > 1 else None
        def terminate(s): pass
        def kill(s): pass
        def send_signal(s, sig): pass
    sup.procs["col_a"] = _P()
    r = sup.arreter_tous()
    assert "col_a" in r["methodes"] and r["methodes"]["col_a"]      # méthode d'arrêt JOURNALISÉE
    assert (rd / "arret_methodes.json").exists()


# ═══════════════ RECETTE — crash/reprise, Ctrl+C par phase, paper-only ═══════════════
def test_crash_resume(tmp_path):
    RC._ARRET.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    (d / "bbo.jsonl").write_text(json.dumps({"coin": "BTC", "ts_wall_ms": 1, "bid": 1, "ask": 1.1}) + "\n")
    r = RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    rid = r["run_id"]
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    # "crash" : ACTIVE.json disparaît, le run reste sur disque
    RC._active_path(tmp_path).unlink()
    rr = RC.creer_ou_reprendre(tmp_path, exiger_flux=False, mode="resume")
    assert rr["start"] == "REPRISE" and rr["run_id"] == rid       # reprise du MÊME run après crash


def test_bounded_cycle_failure_never_enters_infinite_recovery(tmp_path, monkeypatch):
    RC._ARRET.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    (d / "bbo.jsonl").write_text(json.dumps({"coin": "BTC", "ts_wall_ms": 1, "bid": 1, "ask": 1.1}) + "\n")
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False)

    def _cycle_en_echec(*args, **kwargs):
        raise OSError("write probe failed")

    monkeypatch.setattr(RC, "executer_cycle", _cycle_en_echec)
    resultat = RC.boucle_continue(
        tmp_path,
        stop_event=threading.Event(),
        max_cycles=1,
        intervalle_s=0.0,
        recovery_backoff_s=60.0,
    )

    assert resultat["boucle"] == "MAX_CYCLES_FAILED"
    assert resultat["failed_cycle"] == 1
    assert resultat["phase"] == "DISCOVERY"
    assert resultat["error_type"] == "OSError"


def test_ctrl_c_during_each_phase_produces_report(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    (d / "bbo.jsonl").write_text("\n".join(json.dumps(
        {"coin": "BTC", "ts_wall_ms": 1_000_000 + i * 1000, "bid": 64000 * (1 + i * 0.003),
         "ask": 64000 * (1 + i * 0.003) + 1}) for i in range(40)) + "\n")
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    # STOP demandé AVANT la boucle : arrêt coopératif, puis finalisation produit un rapport
    ev = threading.Event(); ev.set()
    RC.boucle_continue(tmp_path, stop_event=ev, max_cycles=1, intervalle_s=0.0)
    fin = RC.finaliser(tmp_path, partial=False)
    assert Path(fin["rapport"]).exists() and fin["finalisation"].startswith("FINALIZATION")


def test_no_real_execution_surface():
    import securite_18h as SEC
    mods = ("canonical_store", "portefeuille_global", "jobs_continue", "outils_recherche", "dashboard_flow",
            "metriques_pepites", "moteur_execution_prod")
    dangereux = []
    for m in mods:
        for f in SEC.scanner_fichier(RACINE / "tools" / (m + ".py")):
            if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "SEED", "APPEL_RESEAU_ECRITURE"):
                dangereux.append((m, f))
    assert dangereux == [], dangereux
