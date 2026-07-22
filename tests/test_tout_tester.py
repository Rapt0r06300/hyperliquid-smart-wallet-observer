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

import pytest

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


def test_courir_TUE_TOUT_L_ARBRE_pas_seulement_le_parent():
    """🔴 22/07 — le budget doit tuer TOUTE la descendance. Un parent qui SPAWN un enfant dormeur
    (héritant du tube) puis dort : si on ne tuait que le parent, le petit-enfant garderait le tube
    ouvert et `_courir` pendrait ~30 s. Le tueur d'arbre (`_tuer_arbre`) doit couper net -> BUDGET
    rapide. C'est la correction du blocage 'recherche 114 min sur budget 90'."""
    import sys as _s
    code = ("import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)']); "
            "time.sleep(90)")
    T._planifier(["tests"])
    r = T._courir("tests", [_s.executable, "-c", code], 2)
    assert r["statut"] == "BUDGET" and r["duree_s"] < 15.0, r


def test_tuer_arbre_sur_None_est_sans_effet():
    T._tuer_arbre(None)          # idempotent / défensif : jamais un plantage


def test_courir_TIMEOUT_dur_meme_sans_sortie():
    """Un sous-processus figé SANS rien afficher doit quand même être coupé (Timer), sinon
    l'audit tournerait à l'infini — un plantage silencieux d'un autre genre."""
    import sys as _s
    r = T._courir("tests", [_s.executable, "-c", "import time; time.sleep(10)"], 1)
    assert r["statut"] == "BUDGET" and r["duree_s"] < 5.0


def test_pytest_parallele_est_SERIE_par_defaut(monkeypatch):
    """🔴 22/07 — le parallèle xdist est OPT-IN : par défaut SÉRIE (une flake de contamination
    inter-fichiers sous parallèle sur Windows ; sans régression > plus vite). Même xdist présent
    et 8 cœurs : rien tant que TOUT_TESTER_PYTEST_PARALLELE n'est pas armé."""
    monkeypatch.delenv("TOUT_TESTER_PYTEST_PARALLELE", raising=False)
    import importlib.util as _iu
    import os as _os
    monkeypatch.setattr(_iu, "find_spec", lambda *_a, **_k: object())   # xdist 'présent'
    monkeypatch.setattr(_os, "cpu_count", lambda: 8)
    assert T._pytest_parallele() == []                      # défaut = série


def test_pytest_parallele_S_ACTIVE_explicitement(monkeypatch):
    """Armé + xdist + multi-cœurs : parallèle avec loadfile (fichier = 1 worker)."""
    import importlib.util as _iu
    import os as _os
    monkeypatch.setenv("TOUT_TESTER_PYTEST_PARALLELE", "1")
    monkeypatch.setattr(_iu, "find_spec", lambda *_a, **_k: object())   # xdist 'présent'
    monkeypatch.setattr(_os, "cpu_count", lambda: 8)
    assert T._pytest_parallele() == ["-n", "auto", "--dist", "loadfile"]
    # armé mais xdist absent -> repli série (jamais un run cassé)
    monkeypatch.setattr(_iu, "find_spec", lambda *_a, **_k: None)
    assert T._pytest_parallele() == []


def test_entete_progres_montre_l_etape_et_le_reste(capsys):
    T._planifier(["securite", "tests", "recherche"])
    T._entete_progres("securite")
    out = capsys.readouterr().out
    assert "étape 1/3" in out and "reste" in out and "estimé" in out


# ═══════════════ HUD « à la seconde » (22/07) : la progression doit VRAIMENT bouger ═══════════════

def _armer_hud(nom="recherche", est=1800.0, ecoule=0.0, budget=5400.0, restant=None, tick=0):
    """Place le HUD dans un état connu pour juger l'affichage SANS lancer de sous-processus."""
    import time as _t
    T._PLAN["restant"] = {} if restant is None else dict(restant)
    T._PLAN["total"] = 6
    T._HUD.update({"actif": True, "nom": nom, "i": 5, "total": 6,
                   "t_etape": _t.time() - ecoule, "budget": budget, "est": est,
                   "derniere": "", "n": 0, "tick": tick})


def test_hud_texte_montre_etape_barre_et_reste_run():
    _armer_hud(nom="recherche", est=1800.0, ecoule=60.0, budget=5400.0,
               restant={"sante": 120})
    txt = T._hud_texte(160)
    assert "étape 5/6" in txt and "recherche" in txt
    assert "reste run" in txt and "budget" in txt and "%" in txt
    assert txt[0] in T._SPINNER                      # un spinner en tête = ça vit


def test_hud_le_reste_run_DECROIT_seconde_apres_seconde():
    """Le cœur de la demande : le temps restant se met à jour. À 10 s d'intervalle simulé, il
    doit avoir baissé d'~10 s (l'étape courante consomme le budget du run)."""
    _armer_hud(est=1800.0, ecoule=0.0, restant={"sante": 120})
    r0 = T._reste_run_s()
    _armer_hud(est=1800.0, ecoule=10.0, restant={"sante": 120})
    r10 = T._reste_run_s()
    assert r0 - r10 == pytest.approx(10.0, abs=1.5), (r0, r10)


def test_hud_le_spinner_change_a_chaque_tick():
    _armer_hud(tick=0)
    a = T._hud_texte(120)[0]
    _armer_hud(tick=1)
    b = T._hud_texte(120)[0]
    assert a != b and a in T._SPINNER and b in T._SPINNER


def test_hud_ne_se_fige_pas_a_zero_quand_l_etape_deborde():
    """Le bug repéré par Flo (« reste run ~0:15 » pendant une recherche ENCORE active) : quand
    l'étape déborde son estimé, on ne réduit PLUS le reste aux seules étapes suivantes — on le
    BORNE par le budget (plafond honnête), avec le signe ≤, et on l'annonce."""
    _armer_hud(nom="tests", est=10.0, ecoule=40.0, budget=60.0, restant={"rapport_jour": 15})
    txt = T._hud_texte(180)
    assert "au-delà de l'estimé" in txt and "≤" in txt
    # plafond = étapes suivantes (15) + budget restant de l'étape (60-40=20) = 35 ; jamais 0 ni 15 seul
    assert T._reste_run_s() == pytest.approx(35.0, abs=2.0) and T._reste_run_s() > 15.0


def test_hud_texte_est_TRONQUE_a_la_largeur_pour_ne_pas_casser_le_retour_chariot():
    _armer_hud()
    T._HUD["derniere"] = "x" * 500          # une très longue dernière ligne
    for largeur in (60, 100, 200):
        assert len(T._hud_texte(largeur)) <= largeur - 1


def test_hud_imprimer_ligne_met_a_jour_le_dernier_ET_capture(capsys):
    """En sortie capturée (non-TTY, comme ici) : comportement d'origine (la ligne sort telle
    quelle pour le RECAP) ET le HUD retient la dernière ligne non vide."""
    _armer_hud()
    T._HUD["n"] = 0
    T._hud_imprimer_ligne("  1234 passed in 42s\n")
    out = capsys.readouterr().out
    assert "1234 passed" in out                      # la sortie réelle n'est jamais avalée
    assert T._HUD["derniere"] == "1234 passed in 42s" and T._HUD["n"] == 1


def test_hud_ETA_MESUREE_depuis_l_avancement_reel():
    """Quand l'étape émet '… avancement i/n configs', le HUD calcule un temps restant sur la
    VITESSE observée (pas la constante). C'est la demande de Flo : 'temps estimé ultra précis'."""
    import time as _t
    _armer_hud(nom="recherche", est=2700.0, ecoule=30.0)
    T._hud_imprimer_ligne("=== module copy (2/5) ===\n")     # nouveau module -> reset compteur
    T._HUD["t_module"] = _t.time() - 10.0                    # simule 10 s écoulées sur ce module
    T._hud_imprimer_ligne("  … avancement 100/1100 configs\n")
    assert T._HUD["fait"] == 100 and T._HUD["total_iter"] == 1100
    txt = T._hud_texte(220)
    assert "MESURÉ 100/1100" in txt and "reste ≈" in txt     # ~10/s -> reste ~1:40


def test_hud_nouveau_module_remet_la_mesure_a_zero():
    _armer_hud(nom="recherche")
    T._HUD.update({"fait": 500, "total_iter": 1100})
    T._hud_imprimer_ligne("=== module arbitrage (3/5) ===\n")
    assert T._HUD["fait"] == 0 and T._HUD["total_iter"] == 0   # la mesure repart proprement


def test_hud_demarrer_puis_arreter_est_idempotent_et_propre():
    T._planifier(["securite", "tests"])
    T._entete_progres("securite")
    T._hud_demarrer("tests", 300.0)
    assert T._HUD["actif"] is True and T._HUD["nom"] == "tests" and T._HUD["est"] == 300.0
    T._hud_arreter()
    assert T._HUD["actif"] is False and T._HUD["thread"] is None
    T._hud_arreter()                                 # deux fois de suite = aucun plantage
