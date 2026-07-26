"""Labo de recherche CONTINU : plusieurs cycles sans limite, nouvelles données consommées, pas de double
comptage, dashboard non nul, durée affichée, Ctrl+C propre puis partiel, stop==Ctrl+C, snapshot sans arrêt,
reprise après crash, campagnes séparées + gel inchangé, rapport final + manifeste, 14h/18h intacts, paper-only."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import recherche_continue as RC   # noqa: E402
import dashboard_continue as DASH  # noqa: E402
import securite_18h as SEC        # noqa: E402


def _bbo(c, ts, mid):
    sp = mid * 0.0006
    return {"venue": "HL", "coin": c, "ts_wall_ms": ts, "bid": mid - sp / 2, "ask": mid + sp / 2, "isSnapshot": False}


def _donnees(root: Path, n=120, decal=0):
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    lignes = [_bbo(c, 1_000_000 + (decal + i) * 1000, base * (1 + (decal + i) * 0.001))
              for i in range(n) for c, base in (("BTC", 64000), ("ETH", 3200))]
    (d / "bbo_tape.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")


def _run(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    _donnees(tmp_path)
    r = RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    return Path(r["rundir"])


def test_plusieurs_cycles_sans_limite_temporelle(tmp_path):
    rd = _run(tmp_path)
    res = RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=2, intervalle_s=0.0)
    assert res["cycles"] == 2
    camps = sorted((rd / "campagnes").glob("camp-*"))
    assert len(camps) == 2                       # 1 campagne par cycle, aucune limite de durée codée en dur


def test_nouvelles_donnees_consommees_entre_cycles(tmp_path):
    rd = _run(tmp_path)
    RC._maj_curseurs_et_nouveaute(tmp_path, rd)   # 1er passage : curseurs posés
    n2, _ = RC._maj_curseurs_et_nouveaute(tmp_path, rd)
    assert n2 is False                            # rien de neuf -> pas de nouveauté
    _donnees(tmp_path, n=160, decal=200)          # de NOUVELLES données arrivent
    n3, _ = RC._maj_curseurs_et_nouveaute(tmp_path, rd)
    assert n3 is True                             # détectées


def test_pas_de_double_comptage_campagnes_separees(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=2, intervalle_s=0.0)
    camps = sorted((rd / "campagnes").glob("camp-*"))
    # chaque campagne a SON ledger séparé (pas de fusion/double comptage)
    l0 = (camps[0] / "ledger" / "trials_results.jsonl")
    l1 = (camps[1] / "ledger" / "trials_results.jsonl")
    assert l0.exists() and l1.exists() and camps[0].name != camps[1].name


def test_dashboard_compteurs_non_nuls_et_duree(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    etat = json.loads((rd / "LIVE-RESEARCH-STATE.json").read_text())
    assert etat["totaux"]["fast_screen"] > 0 and etat["totaux"]["exact_replays"] > 0
    assert "jours" in etat["duree"] and etat["duree_totale_s"] >= 0
    txt = DASH.rendre_texte(etat)
    assert "HYPERSMART" in txt and "duree travail" in txt and str(etat["totaux"]["fast_screen"]) in txt


def test_premier_ctrlc_arret_propre_puis_rapport(tmp_path):
    _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    fin = RC.finaliser(tmp_path, partial=False)   # 1er Ctrl+C = arrêt propre
    assert fin["finalisation"] in ("FINALIZATION_COMPLETE", "FINALIZATION_COMPLETE_WITH_EXCLUSIONS")
    assert Path(fin["rapport"]).exists()
    man = json.loads(Path(fin["manifeste"]).read_text())
    assert man["contient_rapport"] and any("RAPPORT" in k for k in man["fichiers"])
    assert RC._active_path(tmp_path).exists() is False   # ACTIVE supprimé car cohérent


def test_second_ctrlc_rapport_partiel(tmp_path):
    _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    fin = RC.finaliser(tmp_path, partial=True)    # 2e Ctrl+C = urgence
    assert fin["finalisation"] == "FINALIZATION_PARTIAL"
    md = Path(fin["rapport"]).read_text(encoding="utf-8")
    assert "FINALIZATION_PARTIAL" in md and "Aucune perte silencieuse" in md


def test_stop_run_id_egale_ctrlc(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    ident = json.loads((rd / "run_identity.json").read_text())
    fin = RC.stopper(tmp_path, ident["run_id"])
    assert fin["finalisation"].startswith("FINALIZATION_COMPLETE")   # même finalisation propre


def test_snapshot_sans_arreter(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    snap = RC.snapshot(tmp_path)
    assert snap["snapshot"] == "OK" and Path(snap["chemin"]).exists()
    assert RC._active_path(tmp_path).exists()      # le run reste ACTIF (snapshot n'arrête pas)
    assert "SNAPSHOT" in Path(snap["chemin"]).read_text(encoding="utf-8")


def test_reprise_apres_crash_meme_run_id(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    run_id = json.loads((rd / "run_identity.json").read_text())["run_id"]
    # "crash" : on relance creer_ou_reprendre -> REPRISE du même run, cycle préservé
    r2 = RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    assert r2["start"] == "REPRISE" and r2["run_id"] == run_id
    assert json.loads(RC._active_path(tmp_path).read_text())["cycle_courant"] >= 1


def test_campagnes_separees_et_gel_inchange(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=2, intervalle_s=0.0)
    camps = sorted((rd / "campagnes").glob("camp-*"))
    f0 = camps[0] / "resultats" / "CANDIDATES_FROZEN.json"
    avant = f0.read_text() if f0.exists() else None
    # 3e cycle : ne doit PAS modifier le gel de la campagne 0
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=3, intervalle_s=0.0)
    apres = f0.read_text() if f0.exists() else None
    assert avant == apres                          # candidat figé jamais modifié silencieusement


def test_14h_18h_intacts_et_isolation_continue(tmp_path):
    root = Path(__file__).resolve().parents[1]
    # le continu n'écrit que sous continuous/
    txt = (root / "tools" / "recherche_continue.py").read_text(encoding="utf-8")
    assert "continuous" in txt and "overnight_18h" not in txt and "overnight_14h" not in txt
    assert (root / "LANCER-RECHERCHE-14H.cmd").exists() and (root / "LANCER-RECHERCHE-18H.cmd").exists()


def test_securite_paper_only_chaine_continue():
    root = Path(__file__).resolve().parents[1]
    findings = []
    for nom in ("recherche_continue", "dashboard_continue", "rapport_continue"):
        findings += SEC.scanner_fichier(root / "tools" / (nom + ".py"))
    dangereux = [f for f in findings if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "APPEL_RESEAU_ECRITURE", "SEED")]
    assert dangereux == [], dangereux
