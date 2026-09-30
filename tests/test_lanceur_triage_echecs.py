"""LE TRIAGE DES ÉCHECS — que TOUT-TESTER te montre ses ratés, sans scroller (21/07).

Le 21/07, Flo a envoyé TROIS captures d'écran de la fenêtre pour lister les 53 tests FAILED à
la main. Le RECAP les contenait déjà. Le lanceur les extrait désormais, dit ce qui est NOUVEAU
(régression) vs RÉPARÉ depuis la fois d'avant, et affiche le bloc à copier. Un audit qui te
fait chercher ses propres résultats fait la moitié du travail.
"""
from __future__ import annotations

import json

import pytest

from tools import lanceur_tout_tester as L

RECAP_DEMO = """# RÉCAPITULATIF COMPLET

## Étapes
| tests | 🔴 ECHEC | 300 s | 53 failed, 5661 passed |

## Sorties détaillées
<details><summary>tests — ECHEC</summary>

```
FAILED tests/test_carry_positions_store.py::test_ledger_est_append_only
FAILED tests/test_dashboard_v2_coherence.py::test_la_courbe_INCLUT_le_net_carry
FAILED tests/test_invariants_economiques.py::test_L6_un_aller_retour[15.0]
53 failed, 5661 passed in 494.10s
```
</details>
"""


def _ecrire_recap(tmp_path, txt=RECAP_DEMO):
    p = tmp_path / "RECAP-COMPLET.md"
    p.write_text(txt, encoding="utf-8")
    return p


# ─────────────── l'extraction ───────────────

def test_les_tests_FAILED_sont_extraits_du_recap(tmp_path):
    r = L.resumer_echecs_du_recap(_ecrire_recap(tmp_path))
    assert r["present"] is True
    assert r["n_failed"] == 53 and r["n_passed"] == 5661
    assert "test_ledger_est_append_only" in r["failed"][0] or any(
        "append_only" in f for f in r["failed"])
    assert len(r["failed"]) == 3
    assert all(f.startswith("tests/") and "::" in f for f in r["failed"])


def test_un_recap_absent_ne_LEVE_pas(tmp_path):
    r = L.resumer_echecs_du_recap(tmp_path / "n_existe_pas.md")
    assert r["present"] is False and r["failed"] == [] and r["n_failed"] == 0


def test_un_recap_VERT_ne_liste_aucun_echec(tmp_path):
    p = _ecrire_recap(tmp_path, "## tout vert\n```\n5714 passed in 480s\n```\n")
    r = L.resumer_echecs_du_recap(p)
    assert r["n_failed"] == 0 and r["failed"] == [] and r["n_passed"] == 5714


def test_un_nom_de_test_CITE_sans_FAILED_n_est_pas_compte(tmp_path):
    """On n'attrape que les vraies lignes FAILED, pas un nom de test mentionné en prose."""
    p = _ecrire_recap(tmp_path, "```\nvoir tests/test_foo.py::test_bar pour le contexte\n"
                                "1 passed\n```\n")
    r = L.resumer_echecs_du_recap(p)
    assert r["failed"] == []


# ─────────────── le diff vs la fois d'avant ───────────────

def test_le_diff_distingue_NOUVEAUX_REPARES_PERSISTANTS(tmp_path):
    # 1er run : A et B echouent
    d1 = L.comparer_aux_echecs_precedents(["tests/x.py::A", "tests/x.py::B"], tmp_path)
    assert d1["avait_un_precedent"] is False           # rien avant -> pas de faux « nouveau »
    # 2e run : B persiste, C est NEUF, A est REPARE
    d2 = L.comparer_aux_echecs_precedents(["tests/x.py::B", "tests/x.py::C"], tmp_path)
    assert d2["avait_un_precedent"] is True
    assert d2["nouveaux"] == ["tests/x.py::C"]
    assert d2["repares"] == ["tests/x.py::A"]
    assert d2["persistants"] == ["tests/x.py::B"]


def test_un_run_VERT_apres_des_echecs_les_declare_tous_REPARES(tmp_path):
    L.comparer_aux_echecs_precedents(["tests/x.py::A", "tests/x.py::B"], tmp_path)
    d = L.comparer_aux_echecs_precedents([], tmp_path)
    assert sorted(d["repares"]) == ["tests/x.py::A", "tests/x.py::B"]
    assert d["nouveaux"] == []


def test_un_etat_precedent_illisible_ne_fabrique_pas_de_faux_nouveaux(tmp_path):
    chemin = tmp_path / L.ETAT_ECHECS.relative_to(L.RACINE)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("{cassé", encoding="utf-8")
    d = L.comparer_aux_echecs_precedents(["tests/x.py::A"], tmp_path)
    assert d["nouveaux"] == [] and d["avait_un_precedent"] is False


# ─────────────── le bloc affiché ───────────────

def test_le_bloc_de_triage_marque_les_regressions(tmp_path):
    resume = {"failed": ["tests/x.py::A", "tests/x.py::B"], "n_failed": 2}
    diff = {"nouveaux": ["tests/x.py::B"], "repares": ["tests/x.py::Z"],
            "persistants": ["tests/x.py::A"], "avait_un_precedent": True}
    bloc = "\n".join(L.lignes_de_triage(resume, diff))
    assert "ÉCHECS (2)" in bloc
    assert "🆕 tests/x.py::B" in bloc, "une regression doit etre marquee"
    assert "🆕 tests/x.py::A" not in bloc, "un echec deja connu n'est pas une regression"
    assert "repare : tests/x.py::Z" in bloc
    assert "copie ce bloc a Claude" in bloc


def test_le_bloc_de_triage_dit_quand_tout_est_vert():
    bloc = "\n".join(L.lignes_de_triage({"failed": [], "n_failed": 0}))
    assert "aucun test en echec" in bloc


def test_les_options_de_triage_sont_reconnues():
    for o in ("--derniers-echecs", "--sans-triage"):
        assert o in L.OPTIONS_LANCEUR
    # elles restent des options du LANCEUR, jamais transmises au driver
    from tools.tout_tester import OPTIONS
    assert "--derniers-echecs" not in OPTIONS and "--sans-triage" not in OPTIONS


def test_derniers_echecs_ne_relance_rien(tmp_path, monkeypatch, capsys):
    """`--derniers-echecs` lit le dernier RECAP et sort — il ne doit JAMAIS lancer pytest."""
    _ecrire_recap(tmp_path)
    monkeypatch.setattr(L, "_pause", lambda: None)
    # si lancer() tentait de lancer l'orchestrateur, ce subprocess exploserait le test :
    monkeypatch.setattr(L.subprocess, "run",
                        lambda *a, **k: pytest.fail("ne doit RIEN lancer"))
    code = L.lancer(["--derniers-echecs", "--sans-pause"], racine=tmp_path)
    sortie = capsys.readouterr().out
    assert code == 1                                    # il y avait des echecs dans le RECAP
    assert "ÉCHECS (53)" in sortie
