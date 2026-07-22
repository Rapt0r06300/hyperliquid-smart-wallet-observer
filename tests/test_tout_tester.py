"""TOUT-TESTER (21/07) — l'orchestrateur unique doit TOUJOURS rendre son recap.

Trois exigences, chacune payee au moins une fois dans ce projet :
  * une etape qui explose n'arrete pas les suivantes (nuit du 20-21/07 : copy mort en
    silence -> AUCUN rapport) ;
  * un budget par etape (un test qui pend ne mange plus la soiree) ;
  * le recap existe MEME apres une interruption, et il ne ment pas sur ce qui n'a pas tourne.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tout_tester", RACINE / "tools" / "tout_tester.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


def test_le_recap_liste_TOUTES_les_etapes_avec_leur_statut(tmp_path):
    etapes = [
        {"etape": "securite", "statut": "OK", "duree_s": 3.0, "sortie": "aucun ordre reel"},
        {"etape": "tests", "statut": "ECHEC", "duree_s": 120.0, "sortie": "2 failed, 800 passed",
         "resume": "2 failed, 800 passed"},
        {"etape": "recherche", "statut": "BUDGET", "duree_s": 5400.0, "sortie": "BUDGET DEPASSE"},
    ]
    p = T.ecrire_recap(etapes, {"positions_carry": 11, "cross_venue_h": 46.6},
                       chemin=tmp_path / "RECAP-COMPLET.md")
    t = p.read_text(encoding="utf-8")
    for morceau in ("securite", "tests", "recherche", "✅", "🔴", "⏱️",
                    "2 failed, 800 passed", "Sécurité : 0 ordre réel"):
        assert morceau in t, morceau
    assert "11 position" in t and "46.6 h / 72 h" in t
    assert not list(p.parent.glob("*.tmp")), "ecriture atomique : aucun tmp ne traine"


def test_une_etape_qui_explose_devient_ERREUR_sans_tuer_le_reste():
    r = T._courir("bidon", ["python", "-c", "raise SystemExit(3)"], 30)
    assert r["statut"] == "ECHEC" and r["code"] == 3
    r2 = T._courir("introuvable", ["binaire_qui_n_existe_pas_du_tout"], 30)
    assert r2["statut"] == "ERREUR"           # capture, jamais une exception qui remonte


def test_le_budget_coupe_une_etape_qui_pend():
    r = T._courir("qui_pend", ["python", "-c", "import time; time.sleep(30)"], 2)
    assert r["statut"] == "BUDGET" and "BUDGET DEPASSE" in r["sortie"]


def test_le_resume_pytest_est_extrait_de_la_sortie():
    assert "3 failed, 801 passed" in T._resume_pytest(
        "bla\n=========== 3 failed, 801 passed in 42.10s ============\n")
    assert T._resume_pytest("rien du tout") == "résumé introuvable"


def test_le_cmd_unique_pointe_sur_l_orchestrateur():
    # 🔴 21/07 — le .cmd pointe desormais sur le LANCEUR (lanceur_tout_tester.py), pas
    # directement sur l'orchestrateur : apres deux plantages batch, toute la logique (pre-vol,
    # securite, tracabilite) est passee en Python testable. Le lanceur, lui, appelle bien
    # l'orchestrateur tout_tester.py. La chaine .cmd -> lanceur -> orchestrateur est verifiee.
    c = open(RACINE / "TOUT-TESTER.cmd", encoding="utf-8", errors="replace").read()
    assert "tools\\lanceur_tout_tester.py" in c, "le .cmd appelle le lanceur Python"
    lanceur = open(RACINE / "tools" / "lanceur_tout_tester.py", encoding="utf-8").read()
    assert "tout_tester.py" in lanceur, "le lanceur appelle bien l'orchestrateur"
    assert "RECAP-COMPLET.md" in c or "RECAP" in lanceur
    assert "--rapide" in c, "l'option courte doit etre documentee dans l'en-tete"


# ---------------- 21/07 : le recap doit SERVIR le PnL, pas lister des etapes ----------------

def test_l_attribution_dit_OU_va_l_argent_par_strategie_et_par_motif(tmp_path):
    import json, time
    d = tmp_path / "runtime" / "data"; d.mkdir(parents=True)
    now = time.time() * 1000
    (d / "carry_paper_ledger.jsonl").write_text("\n".join([
        json.dumps({"kind": "CLOSE", "strategie": "carry", "reason": "CHURN",
                    "ts_ms": now - 3600_000, "realized_net_pnl_usdc": -0.30}),
        json.dumps({"kind": "CLOSE", "strategie": "arbitrage", "reason": "ARB_CONVERGENCE",
                    "ts_ms": now - 7200_000, "realized_net_pnl_usdc": 0.08}),
        json.dumps({"kind": "CLOSE", "strategie": "carry", "reason": "VIEUX",
                    "ts_ms": now - 30 * 24 * 3600_000, "realized_net_pnl_usdc": -99.0}),
    ]) + "\n", encoding="utf-8")
    a = T.attribution_pnl(tmp_path)
    assert a["n_fermetures"] == 2, "la fenetre 24 h exclut la vieille epoque"
    assert a["par_strategie"] == {"arbitrage": 0.08, "carry": -0.3}
    assert abs(a["total_24h"] - (-0.22)) < 1e-9


def test_le_plan_d_action_designe_le_motif_le_plus_couteux():
    attrib = {"n_fermetures": 3, "total_24h": -0.5,
              "par_motif": {"CHURN": -0.4, "BASE": -0.1}, "par_strategie": {}}
    plan = "\n".join(T.plan_action_pnl([], {"cross_venue_h": 46.6}, attrib))
    assert "CHURN" in plan and "le plus coûteux" in plan
    assert "46.6 h / 72 h" in plan and "ne rien conclure avant" in plan


def test_le_plan_reclame_le_verdict_quand_la_mesure_est_MURE():
    plan = "\n".join(T.plan_action_pnl([], {"cross_venue_h": 73.0}, {"n_fermetures": 0}))
    assert "verdict est mûr" in plan


def test_le_plan_signale_les_collecteurs_muets_et_les_tests_rouges():
    etapes = [{"etape": "tests", "statut": "ECHEC", "resume": "2 failed", "sortie": ""}]
    sante = {"collecteurs_age_s": {"marks-collector": 9999, "carry-feeder": 60}}
    plan = "\n".join(T.plan_action_pnl(etapes, sante, {"n_fermetures": 0}))
    assert "marks-collector" in plan and "carry-feeder" not in plan.split("Santé")[1][:200]
    assert "2 failed" in plan and "AVANT d'ajouter" in plan


def test_le_recap_commence_par_le_plan_et_compare_au_passage_precedent(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "HISTORIQUE", tmp_path / "hist.jsonl")
    etapes = [{"etape": "tests", "statut": "OK", "duree_s": 10.0, "sortie": "ok",
               "resume": "800 passed"}]
    sante = {"realise_total": -6.05, "positions_carry": 11, "cross_venue_h": 46.6}
    p1 = T.ecrire_recap(etapes, sante, chemin=tmp_path / "R1.md")
    t1 = p1.read_text(encoding="utf-8")
    assert t1.index("PLAN D'ACTION") < t1.index("| Étape |"), "le plan passe AVANT les etapes"
    assert "Premier passage" in t1
    sante2 = dict(sante, realise_total=-5.0, positions_carry=12)
    t2 = T.ecrire_recap(etapes, sante2, chemin=tmp_path / "R2.md").read_text(encoding="utf-8")
    assert "▲" in t2, "la progression se voit d'un coup d'oeil"
    assert (tmp_path / "hist.jsonl").read_text(encoding="utf-8").count("\n") == 2


# ═══════════════ VITESSE & VISIBILITÉ (22/07) ═══════════════

def test_mmss_est_lisible():
    assert T._mmss(0) == "0:00" and T._mmss(75) == "1:15" and T._mmss(-3) == "0:00"


def test_courir_STREAME_et_CAPTURE_a_la_fois():
    """🔴 « voir tout ce qui se passe » : l'ancien _courir capturait tout et n'affichait qu'à la
    fin (écran figé 53 min pendant la recherche). Le nouveau STREAME en direct ET capture pour
    le RECAP. On vérifie la capture (le stream est prouvé par le smoke)."""
    import sys as _s
    T._planifier(["securite", "tests"])
    r = T._courir("securite", [_s.executable, "-c", "print('AA'); print('BB')"], 30)
    assert r["statut"] == "OK" and "AA" in r["sortie"] and "BB" in r["sortie"]


def test_courir_TIMEOUT_dur_meme_sans_sortie():
    """Un sous-processus figé SANS rien afficher doit quand même être coupé (Timer), sinon
    l'audit tournerait à l'infini — un plantage silencieux d'un autre genre."""
    import sys as _s
    r = T._courir("tests", [_s.executable, "-c", "import time; time.sleep(10)"], 1)
    assert r["statut"] == "BUDGET" and r["duree_s"] < 5.0


def test_pytest_parallele_repli_SERIE_est_sur(monkeypatch):
    """Coupe-circuit + repli : jamais un run cassé pour aller vite."""
    monkeypatch.setenv("TOUT_TESTER_PYTEST_SERIE", "1")
    assert T._pytest_parallele() == []                      # forcé série
    monkeypatch.delenv("TOUT_TESTER_PYTEST_SERIE", raising=False)
    import importlib.util as _iu
    monkeypatch.setattr(_iu, "find_spec", lambda *_a, **_k: None)  # xdist 'absent'
    assert T._pytest_parallele() == []                      # repli série si xdist manque


def test_pytest_parallele_donne_loadfile_si_dispo(monkeypatch):
    """Quand xdist est là et la machine multi-cœurs : parallèle avec loadfile (fichier = 1 worker)."""
    import importlib.util as _iu
    import os as _os
    monkeypatch.delenv("TOUT_TESTER_PYTEST_SERIE", raising=False)
    monkeypatch.setattr(_iu, "find_spec", lambda *_a, **_k: object())   # xdist 'présent'
    monkeypatch.setattr(_os, "cpu_count", lambda: 8)
    args = T._pytest_parallele()
    assert args == ["-n", "auto", "--dist", "loadfile"]


def test_entete_progres_montre_l_etape_et_le_reste(capsys):
    T._planifier(["securite", "tests", "recherche"])
    T._entete_progres("securite")
    out = capsys.readouterr().out
    assert "étape 1/3" in out and "reste" in out and "estimé" in out
