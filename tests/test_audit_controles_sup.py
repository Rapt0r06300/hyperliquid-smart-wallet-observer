"""CONTRÔLES D'AUDIT SUPPLÉMENTAIRES — les leçons des 18-19/07 doivent MORDRE.

Chaque contrôle testé ici correspond à un bug réel : l'unité ×30 (rotation churnée),
les interrupteurs éteints, la provenance dYdX (3 773 refus fantômes), et le « PROFIT
FACTOR ≥1 » affiché avec −5,44 $ réalisés (screenshot de Flo, 19/07 16:29).
On teste les DEUX sens : le contrôle attrape le poison, ET laisse passer le sain —
un audit qui rougit sur tout est aussi inutile qu'un audit qui ne rougit jamais.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    chemin = RACINE / "tools" / "audit_controles_sup.py"
    spec = importlib.util.spec_from_file_location("audit_controles_sup", chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SUP = _mod()


# ------------------------------------------------------------------ A. unites *_24h*

def test_le_cumul_horizon_deguise_en_24h_est_ATTRAPE():
    """LE BUG DU 19/07, tel quel : affectation _24h_ depuis une expression horizon."""
    src = "gain_net_24h_bps = funding_cumule_bps(horizon_h, f) - cout_entree\n"
    suspects = SUP.trouver_affectations_24h_suspectes(src, "x.py")
    assert len(suspects) == 1 and "x.py:1" in suspects[0]


def test_le_vrai_taux_journalier_PASSE():
    """Division par des jours = vrai taux : le controle ne doit pas crier au loup."""
    src = "gain_net_24h_bps = round(gain_horizon / jours_horizon, 3)\n"
    assert SUP.trouver_affectations_24h_suspectes(src, "x.py") == []


def test_le_marqueur_d_exemption_est_respecte():
    src = "seuil_24h = horizon_h * 2  # audit:unite-ok justification en revue\n"
    assert SUP.trouver_affectations_24h_suspectes(src, "x.py") == []


def test_le_REPO_actuel_est_propre():
    """Après la réparation 1bdbf4a, le code réel ne doit plus contenir ce poison."""
    resume, erreurs = SUP.controle_unites_24h()
    assert erreurs == [], erreurs


# ------------------------------------------------------------------ B. interrupteurs lanceur

def test_le_lanceur_ACTUEL_passe_les_exigences():
    resume, erreurs = SUP.controle_interrupteurs_lanceur()
    assert erreurs == [], erreurs


def test_un_lanceur_sabote_est_ATTRAPE(tmp_path):
    """Exécution réelle activée + plancher à zéro + sniper rouvert : 5+ erreurs attendues."""
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text(
        'set "HL_ENABLE_MAINNET_EXECUTION=1"\n'
        'set "HYPERSMART_SIMULATION_MIN_EDGE_BPS=0"\n'
        'set "HYPERSMART_SUPERVISEUR_COLLECTEURS=0"\n', encoding="utf-8")
    resume, erreurs = SUP.controle_interrupteurs_lanceur(tmp_path)
    assert len(erreurs) >= 5, erreurs         # 4 exigences absentes + 2 interdits presents...
    assert any("fail-open" in e for e in erreurs)
    assert any("famine" in e for e in erreurs)


# ------------------------------------------------------------------ C. provenance dYdX

def test_le_verrou_de_provenance_est_PRESENT():
    resume, erreurs = SUP.controle_provenance_dydx()
    assert erreurs == [], erreurs


def test_un_verrou_retire_est_ATTRAPE(tmp_path):
    p = tmp_path / "src" / "hl_observer" / "simulation"
    p.mkdir(parents=True)
    (p / "log_metrics.py").write_text("AUTORISER_DYDX_LEGACY = True\n", encoding="utf-8")
    resume, erreurs = SUP.controle_provenance_dydx(tmp_path)
    assert len(erreurs) == 1 and "7bd5b43" in erreurs[0]


# ------------------------------------------------------------------ D. chiffre rassurant UI

def test_le_dashboard_ACTUEL_n_a_plus_de_repli_optimiste():
    """Le « ≥1 » du screenshot de Flo est mort ; ce test l'empêche de ressusciter."""
    resume, erreurs = SUP.controle_ui_sans_chiffre_rassurant()
    assert erreurs == [], erreurs


def test_un_repli_optimiste_reintroduit_est_ATTRAPE(tmp_path):
    ui = tmp_path / "src" / "hl_observer" / "ui"
    ui.mkdir(parents=True)
    (ui / "panneau.py").write_text(
        "texte = ok ? valeur : '≥1'  # placebo\n", encoding="utf-8")
    resume, erreurs = SUP.controle_ui_sans_chiffre_rassurant(tmp_path)
    assert len(erreurs) == 1 and "panneau.py:1" in erreurs[0]


# ------------------------------------------------------------------ E. sante runtime

def test_la_sante_runtime_ne_bloque_JAMAIS_et_decrit(tmp_path):
    """Etat operationnel = AVERTISSEMENTS seulement ; et sur un dossier vide, ca decrit
    l'absence au lieu d'exploser (l'audit doit finir meme sur une racine morte)."""
    resume, warns = SUP.controle_sante_runtime(tmp_path)
    assert isinstance(warns, list) and warns, "sur une racine vide, tout collecteur est muet"
    assert "jamais" in resume or "verdict" in resume


def test_la_sante_runtime_du_REPO_liste_le_ledger():
    resume, warns = SUP.controle_sante_runtime(RACINE)
    assert any("ledger carry" in w for w in warns), (
        "la photo doit citer le PnL du ledger comme reference croisee du dashboard")


def test_un_input_carry_absent_ne_masque_pas_un_ledger_present(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "carry_paper_ledger.jsonl").write_text(
        '{"kind":"CLOSE","realized_net_pnl_usdc":1.25}\n', encoding="utf-8"
    )
    _, warns = SUP.controle_sante_runtime(tmp_path)
    assert any("ledger carry = +1.2500" in w for w in warns), warns
