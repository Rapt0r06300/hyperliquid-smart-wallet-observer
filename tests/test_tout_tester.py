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
    c = open(RACINE / "TOUT-TESTER.cmd", encoding="utf-8", errors="replace").read()
    assert "tools\\tout_tester.py" in c and "RECAP-COMPLET.md" in c
    assert "--rapide" in c, "l'option courte doit etre documentee dans l'en-tete"
