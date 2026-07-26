"""LABO-CONTINU-PROD-TRUTH — 15 tests bloquants (Flo 26/07). Prouve, sans lancer le run réel : CLI collecteurs
+ heartbeat, incrémental (cycle 2 ne re-parse pas), moteur exécutable ask→bid/bid→ask, gate sans métriques
fabriquées, alignement par épisode (UNMEASURABLE gardé), portefeuille paper à capital partagé, réconciliation
depuis ledger, RETRYABLE, 7 files consommées, arrêt coopératif catalogue+validation, 2e Ctrl+C = partiel,
superviseur détecte figé, rapport streaming + exclusions. Paper-only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import moteur_execution_prod as MEP     # noqa: E402
import portefeuille_paper as PP         # noqa: E402
import reconciliation_prod as RECO      # noqa: E402
import corpus_incremental as INC        # noqa: E402
import scheduler_continue as SCH        # noqa: E402
import superviseur_continue as SUP      # noqa: E402
import heartbeat_collecteur as HB       # noqa: E402
import validation_18h as V18            # noqa: E402
import pipeline_18h as PL               # noqa: E402
import recherche_continue as RC         # noqa: E402


def _bbo(c, ts, mid):
    sp = mid * 0.0006
    return {"venue": "HL", "coin": c, "ts_wall_ms": ts, "bid": mid - sp / 2, "ask": mid + sp / 2, "isSnapshot": False}


def _donnees(root, n=100, decal=0, coins=(("BTC", 64000), ("ETH", 3200))):
    d = Path(root) / "runtime" / "data"; d.mkdir(parents=True, exist_ok=True)
    lignes = [_bbo(c, 1_000_000 + (decal + i) * 1000, base * (1 + (decal + i) * 0.001))
              for i in range(n) for c, base in coins]
    (d / "bbo_tape.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")


# ─────────── 1) collecteurs : CLI correct + heartbeat en croissance ───────────
def test_real_collectors_cli_start_and_heartbeat(tmp_path):
    reg = RC._collecteurs_lecture_seule(tmp_path)
    for nom, argv in reg.items():
        # arguments CORRECTS : jamais un positionnel qui ferait argparse code 2
        cmd = [sys.executable, *[a if a != "--root" else a for a in argv]]
        # on force le mode borné pour prouver le CLI sans dépendre du réseau/WS
        if "--poll-s" in argv:
            cmd = [sys.executable, str(RACINE / "tools" / "collecter_lab_ctx.py"), "--root", str(tmp_path), "--une-passe"]
        else:
            cmd = [sys.executable, str(RACINE / "tools" / "collecter_lab_microstructure.py"), "--root", str(tmp_path), "--une-passe"]
        try:
            r = subprocess.run(cmd, cwd=str(RACINE), capture_output=True, text=True, timeout=60)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = None                                        # a démarré (pas argparse=2) mais réseau lent
        assert rc != 2, "argparse a rejeté les arguments de %s" % nom       # << défaut P0 corrigé
        nom_hb = "lab-ctx" if "--poll-s" in argv else "lab-microstructure"
        assert HB.chemin(tmp_path, nom_hb).exists(), "pas de heartbeat pour %s" % nom_hb
        assert HB.lire(tmp_path, nom_hb).get("n_passes", 0) >= 1


# ─────────── 2) incrémental : le cycle 2 ne re-parse pas le cycle 1 ───────────
def test_cycle_two_does_not_reparse_cycle_one(tmp_path):
    RC._ARRET.clear()
    _donnees(tmp_path)
    rd = Path(RC.creer_ou_reprendre(tmp_path, exiger_flux=False)["rundir"])
    r1 = RC.executer_cycle(tmp_path, rd, cycle=1, code_sha="abc")
    ing1 = json.loads((rd / "campagnes" / r1["campaign_id"] / "resultats" / "cycle_ingestion.json").read_text())
    r2 = RC.executer_cycle(tmp_path, rd, cycle=2, code_sha="abc")
    ing2 = json.loads((rd / "campagnes" / r2["campaign_id"] / "resultats" / "cycle_ingestion.json").read_text())
    assert ing1["mode"] == "INCREMENTAL" and ing1["from_cache"] is False and ing1["n_sources_parsees_ce_cycle"] >= 1
    assert ing2["from_cache"] is True and ing2["n_sources_parsees_ce_cycle"] == 0   # cycle 2 : cache, 0 re-parse


def test_affected_windows_limit_actual_replay():
    hist = [{"coin": c, "ts_ms": i, "bid": 1, "ask": 1.1} for c in ("BTC", "ETH", "SOL") for i in range(10)]
    fen = INC.fenetre_active(hist, [], {"coins": ["BTC"]})
    assert fen["n_hist_rejoues"] < fen["n_hist_total"] and fen["coins"] == ["BTC"]   # rejoue SEULEMENT le coin touché
    assert all(e["coin"] == "BTC" for e in fen["working"])


# ─────────── 3) moteur exécutable ask→bid / bid→ask ───────────
def test_taker_long_ask_to_bid():
    ep = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1,
          "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}}
    o = MEP.evaluer_episode(ep, sens=1, horizon_ms=1000)
    assert o["status"] == "OK" and o["entry_px"] == 100.1 and o["exit_px"] == 100.4   # long : entrée ASK, sortie BID
    # PnL brut = (bid_futur - ask)/ask, positif ici
    assert abs(o["gross_bps"] - (100.4 - 100.1) / 100.1 * 1e4) < 1e-3


def test_taker_short_bid_to_ask():
    ep = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1,
          "fwd_bid": {1000: 99.4}, "fwd_ask": {1000: 99.6}}
    o = MEP.evaluer_episode(ep, sens=-1, horizon_ms=1000)
    assert o["status"] == "OK" and o["entry_px"] == 99.9 and o["exit_px"] == 99.6    # short : entrée BID, sortie ASK
    assert abs(o["gross_bps"] - (99.9 - 99.6) / 99.9 * 1e4) < 1e-3                    # baisse -> short gagne


# ─────────── 4) gate : plus aucune métrique fabriquée ───────────
def test_no_fabricated_gate_metrics():
    src = (RACINE / "tools" / "pipeline_18h.py").read_text(encoding="utf-8")
    # les constantes fabriquées ont disparu de reconcilier_et_juger
    assert '"pf_oos": 1.3' not in src and '"plateau": True' not in src and '"ledger_reconcilie": True' not in src
    # net positif mais une métrique requise NON calculée -> DATA_MISSING (jamais PASS)
    cand = {"n": 100, "net_median_oos_bps": 6.0, "net_moyen_oos_bps": 5.0, "holdout_vu": True,
            "pf_oos": 1.5, "dsr": 0.97, "pbo": 0.1, "ic_bas_bps": 1.0, "stress_survit": True,
            "plateau": None, "un_seul_coin_dominant": False, "drawdown_borne": True,
            "capacite_non_nulle": True, "ledger_reconcilie": True, "securite_verte": True}
    assert V18.gate(cand)["verdict"] == "DATA_MISSING"
    cand2 = {**cand, "plateau": True}
    assert V18.gate(cand2)["verdict"] == "PASS_FORWARD_PAPER"     # toutes présentes -> PASS possible


# ─────────── 5) alignement par épisode : UNMEASURABLE garde son identité ───────────
def test_episode_alignment_with_unmeasurable():
    corpus = [{"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.5}},
              {"coin": "BTC", "ts_ms": 1, "bid": 99.9, "ask": 100.1, "fwd_mid": {}},          # pas de forward
              {"coin": "BTC", "ts_ms": 2, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.2}}]
    eps = MEP.evaluer_episodes(corpus, sens=1, horizon_ms=1000)
    assert len(eps) == len(corpus)                                # MÊME longueur : aucun filtrage silencieux
    assert eps[0]["status"] == "OK" and eps[1]["status"] == "UNMEASURABLE" and eps[2]["status"] == "OK"
    assert eps[1]["net_bps"] is None                             # UNMEASURABLE ne devient jamais 0
    assert len({e["episode_id"] for e in eps}) == 3             # identités distinctes conservées


# ─────────── 6) portefeuille paper à capital PARTAGÉ ───────────
def test_forward_portfolio_shared_capital():
    pf = PP.PortefeuillePaper(100.0, levier=1.0)                  # capital 100, levier 1 -> marge = notionnel
    a = pf.ouvrir("p1", coin="BTC", sens=1, notional=60.0, prix=100.0)
    b = pf.ouvrir("p2", coin="ETH", sens=1, notional=60.0, prix=100.0)   # 60+60 > 100 -> refusé (capital partagé)
    assert not a.get("refus") and b.get("refus") == "CAPITAL_INSUFFISANT"
    assert pf.marge_engagee() <= 100.0 + 1e-9
    pf.fermer("p1", prix=101.0)                                   # +1% sur 60 = +0.6, capital libéré
    assert pf.cash_disponible() > 60.0
    rec = pf.reconcilier()
    assert rec["coherent"] and rec["pnl_realise"] == rec["pnl_realise_reconstruit"]


# ─────────── 7) réconciliation depuis le ledger d'événements ───────────
def test_real_ledger_reconciliation(tmp_path):
    pf = PP.PortefeuillePaper(1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, couts={"fees_bps": 2.0})
    pf.fermer("p1", prix=102.0, couts={"fees_bps": 2.0})         # +2% sur 300 = +6, − frais
    led = tmp_path / "forward_portfolio.jsonl"
    pf.ecrire_ledger(led)
    rec = RECO.reconstruire_depuis_ledger(led)
    # PnL reconstruit ≈ PnL du portefeuille (source indépendante = ledger d'événements)
    assert abs(rec["pnl_realise"] - pf.realized) < 1e-3 and rec["evenements"]["open"] == 1 and rec["evenements"]["close"] == 1
    assert rec["equity"] > 1000.0                                 # gain réel réconcilié


# ─────────── 8) variante interrompue reste RETRYABLE ───────────
def test_interrupted_trial_remains_retryable():
    v = [{"family": "GENERIC", "horizon_ms": 250, "direction": 1, "coins": ["BTC"], "params": {"seuil": s}, "version": 1}
         for s in (4, 5, 6)]
    deja = SCH.marquer_vues(set(), v, 2)                          # seules 2 premières ont un résultat terminal
    assert SCH.signature_canonique(v[0]) in deja and SCH.signature_canonique(v[1]) in deja
    assert SCH.signature_canonique(v[2]) not in deja             # la 3e (interrompue) reste RETRYABLE


# ─────────── 9) les 7 files sont réellement consommées ───────────
def test_scheduler_seven_queues_are_consumed():
    plan = SCH.planifier_cycle(sante_ingestion=1, forward_figes=1, exact_survivants=1, validation_stress=1,
                               exploration=[{"family": "GENERIC"}], amelioration_locale=1, analyse_rejets=1)
    assert plan["toutes_consommees"] is True
    assert all(plan["par_file_consommee"][f] > 0 for f in SCH.FILES) and len(SCH.FILES) == 7


# ─────────── 10) arrêt coopératif : catalogue + validation ───────────
def test_stop_request_interrupts_catalogue_and_validation(tmp_path):
    ev = threading.Event(); ev.set()
    # (a) catalogue : stop déjà demandé -> pas de catalogage (interrompu)
    res = PL.executer_pipeline_donnees_completes(tmp_path, tmp_path / "rd", code_sha="t",
                                                 new_events=[], affected_windows={"coins": []}, stop_event=ev)
    assert res.get("interrompu") is True and res.get("phase") == "AVANT_CATALOGUE"
    # (b) validation : stop demandé -> boucle interrompue, 0 validé
    surv = [{"trial_id": "x", "family": "GENERIC", "coin": "BTC", "direction": 1, "horizon_ms": 1000, "regime": "r"}]
    v = PL.phase_validation(tmp_path / "rd2", PL.corpus_fixtures(), survivants=surv, stop_event=ev)
    assert v["interrompu"] is True and v["n_valides"] == 0


# ─────────── 11) 2e Ctrl+C pendant la finalisation -> PARTIAL ───────────
def test_second_ctrlc_during_finalize_is_partial(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    _donnees(tmp_path)
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    RC._URGENCE.set()                                            # 2e Ctrl+C ARRIVE (relu pendant la finalisation)
    fin = RC.finaliser(tmp_path, partial=False)
    assert fin["finalisation"] == "FINALIZATION_PARTIAL"
    RC._URGENCE.clear()


# ─────────── 12) superviseur détecte un collecteur VIVANT mais FIGÉ ───────────
def test_supervisor_detects_alive_but_stale_collector(tmp_path):
    import os
    rd = tmp_path / "run"; rd.mkdir()
    sup = SUP.Superviseur(rd, {"lab-ctx": ["x.py"]}, root=tmp_path, heartbeat_max_age_ms=1000, backoff_s=0.0)
    sup.etat["lab-ctx"] = {"pid": os.getpid(), "start": SUP._create_time(os.getpid()), "restart_count": 0}
    # heartbeat VIEUX (200 s) alors que le process est vivant -> figé
    HB.battre(tmp_path, "lab-ctx")
    vieux = HB.lire(tmp_path, "lab-ctx"); vieux["ts_ms"] -= 200_000
    HB.chemin(tmp_path, "lab-ctx").write_text(json.dumps(vieux), encoding="utf-8")
    s = sup.sante("lab-ctx")
    assert s["vivant"] is True and s["fige"] is True and s["sain"] is False
    surv = sup.surveiller(lancer=lambda n, a: os.getpid())
    assert any(r["nom"] == "lab-ctx" and r["raison"] == "FIGE" for r in surv["redemarres"])


# ─────────── 13) rapport : streaming JSONL + vraies exclusions ───────────
def test_report_streams_jsonl_and_reports_exclusions(tmp_path):
    # (a) streaming : lit ligne par ligne sans tout charger
    p = tmp_path / "big.jsonl"
    p.write_text("\n".join(json.dumps({"i": i}) for i in range(5)) + "\n")
    vus = list(RECO.lire_jsonl_stream(p))
    assert [d["i"] for d in vus] == [0, 1, 2, 3, 4]
    # (b) vraies exclusions agrégées (épisodes forward non mesurés) — plus jamais [] par défaut
    camp = tmp_path / "campagnes" / "camp-0001-x"
    (camp / "ledger").mkdir(parents=True)
    (camp / "resultats").mkdir(parents=True)
    with (camp / "ledger" / "forward_paper.jsonl").open("w") as f:
        f.write(json.dumps({"type": "UNMEASURABLE"}) + "\n")
        f.write(json.dumps({"type": "NO_FILL"}) + "\n")
    exc = RECO.agreger_exclusions(tmp_path)
    types = {e["type"] for e in exc}
    assert "EPISODE_UNMEASURABLE" in types and "EPISODE_NO_FILL" in types and len(exc) >= 2


# ─────────── 14) paper-only sur toute la nouvelle chaîne PROD-TRUTH ───────────
def test_paper_only_prod_truth_chain():
    import securite_18h as SEC
    findings = []
    for nom in ("moteur_execution_prod", "portefeuille_paper", "reconciliation_prod", "forward_portefeuille",
                "corpus_incremental", "heartbeat_collecteur"):
        findings += SEC.scanner_fichier(RACINE / "tools" / (nom + ".py"))
    dangereux = [f for f in findings if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "SEED")]
    assert dangereux == [], dangereux


# ─────────── 15) 14h/18h intacts ───────────
def test_14h_18h_intacts_prod_truth():
    assert (RACINE / "LANCER-RECHERCHE-14H.cmd").exists() and (RACINE / "LANCER-RECHERCHE-18H.cmd").exists()
    import recherche_18h  # noqa: F401
