"""#292 / P6b — LE PANNEAU DE SECURITE NE PEUT PLUS MENTIR (2026-07-13).

🔴 CE QUI ETAIT AFFICHE :

    UiRiskGate(name="api stable", passed=True),     # <-- EN DUR. TOUJOURS VERT.

Le dashboard annoncait « api stable ✓ » **que l'API soit stable ou non**. Un voyant vert **soude
en position verte**. C'est ce que P6b nommait : *« le texte affirme des controles absents »* --
et c'est **une donnee fabriquee presentee comme reelle**, sur le panneau SECURITE.

🚩 Le module qui savait la verite existait depuis P12 (`realtime/source_health.py`, « interdire le
faux OK », marque **completed**). **L'interface ne l'a jamais lu.**

LA REGLE : *un gate dont l'etat n'est pas MESURE ne peut pas etre vert. Il est ROUGE, et il dit
pourquoi.* Un « je ne sais pas » honnete fait chercher ; un « tout va bien » fabrique endort.

Aucun ordre reel.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.ui.safety_gates_truth import (
    NON_MESURE,
    gate_inconnu,
    gate_mesure,
    gates_de_securite,
    resume,
)

RACINE = Path(__file__).resolve().parents[1]
ROUTES = RACINE / "src" / "hl_observer" / "ui" / "routes.py"


def _gates_ok(**kw):
    """L'etat NOMINAL : tout est sain, tout est mesure."""
    base = dict(
        mainnet_execution_active=False,
        testnet_execution_active=False,
        est_en_mode_paper=True,
        kill_switch_actif=False,
        base_lisible=True,
        sante_des_sources={
            "status": "HEALTHY", "techniquement_sain": True,
            "produit_des_signaux_frais": True, "reasons": [],
        },
        age_max_source_s=10.0,
    )
    base.update(kw)
    return gates_de_securite(**base)


# ============================================================ 1. L'INVARIANT : PAS DE VERT EN DUR


def test_AUCUN_gate_de_l_UI_ne_peut_naitre_avec_un_passed_True_LITTERAL():
    """🔴 L'INVARIANT QUI REND LE BUG IMPOSSIBLE A REECRIRE.

    On parcourt l'AST de `routes.py` et on cherche toute construction `UiRiskGate(...)` dont
    l'argument `passed` est la **constante litterale `True`**. C'etait le bug exact.

    Un `passed=<expression>` est legitime : il DEPEND de quelque chose. Un `passed=True` ne
    depend de rien -- **c'est une affirmation, pas une mesure.**

    (AST, pas un grep : un grep compterait ce docstring, qui CITE le bug pour l'expliquer.
    On a deja paye cette confusion trois fois aujourd'hui.)
    """
    arbre = ast.parse(ROUTES.read_text(encoding="utf-8"))
    coupables: list[str] = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        nom = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        if nom != "UiRiskGate":
            continue
        for kw in n.keywords:
            if kw.arg == "passed" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value is True:
                coupables.append("ligne %d" % n.lineno)
    assert not coupables, (
        "🔴 gate(s) de securite avec `passed=True` EN DUR : %s.\n"
        "Un voyant vert qui ne depend de rien n'est pas un controle : c'est une AFFIRMATION. "
        "C'est le bug de P6b, et il vient d'etre reintroduit." % ", ".join(coupables)
    )


# ============================================================ 2. UN INCONNU N'EST JAMAIS VERT


def test_une_sante_de_source_INCONNUE_donne_un_gate_ROUGE_pas_vert():
    """Le cœur du correctif. Aucune mesure -> **ROUGE**, avec le motif NON_MESURE."""
    gates = _gates_ok(sante_des_sources=None)
    sources = [g for g in gates if "source" in g.name]
    assert sources, "le gate des sources a disparu du panneau"
    for g in sources:
        assert g.passed is False, "une source dont on ne sait RIEN est affichee VERTE"
        assert NON_MESURE in g.detail


def test_une_base_ILLISIBLE_donne_un_gate_ROUGE_pas_vert():
    gates = _gates_ok(base_lisible=None)
    g = next(g for g in gates if g.name == "base de donnees")
    assert g.passed is False
    assert NON_MESURE in g.detail


def test_une_fraicheur_NON_MESUREE_donne_un_gate_ROUGE():
    gates = _gates_ok(age_max_source_s=None)
    g = next(g for g in gates if "fraicheur" in g.name)
    assert g.passed is False
    assert NON_MESURE in g.detail


# ============================================================ 3. LE GARDE MORD SUR LE DANGER


def test_une_execution_MAINNET_active_fait_ROUGIR_le_panneau():
    """Le gate le plus important du projet. S'il ne peut pas rougir, il ne garde rien."""
    gates = _gates_ok(mainnet_execution_active=True)
    g = next(g for g in gates if "mainnet" in g.name)
    assert g.passed is False


def test_le_kill_switch_ACTIF_fait_ROUGIR_le_panneau():
    gates = _gates_ok(kill_switch_actif=True)
    g = next(g for g in gates if "kill" in g.name)
    assert g.passed is False


def test_une_source_VIVANTE_mais_SANS_SIGNAL_FRAIS_ne_passe_PAS_pour_saine():
    """🔴 LA LECON DE P12, PRESERVEE : « techniquement sain » et « utile » sont DEUX questions.

    Une source peut repondre parfaitement... et ne produire aucun signal frais. Les fondre en un
    seul voyant vert, ce serait refabriquer le mensonge qu'on vient de retirer.
    """
    gates = _gates_ok(sante_des_sources={
        "status": "NO_FRESH_SIGNAL", "techniquement_sain": True,
        "produit_des_signaux_frais": False, "reasons": ["aucun delta depuis 20 min"],
    })
    tech = next(g for g in gates if "techniquement" in g.name)
    frais = next(g for g in gates if "frais" in g.name)
    assert tech.passed is True          # elle repond
    assert frais.passed is False        # ... mais elle ne sert a rien
    r = resume(gates)
    assert r["tout_mesure_et_vert"] is False


# ============================================================ 4. LE RESUME NE FOND PAS LES DEUX


def test_le_resume_distingue_ECHEC_et_NON_MESURE():
    """Ne pas confondre « c'est casse » et « je n'ai pas regarde ». Les deux sont rouges, mais
    ils appellent des actions OPPOSEES : reparer, ou aller mesurer."""
    gates = [
        gate_mesure("a", True, "ok"),
        gate_mesure("b", False, "casse"),
        gate_inconnu("c", "jamais regarde"),
    ]
    r = resume(gates)
    assert r["echecs"] == ["b"]
    assert r["non_mesures"] == ["c"]
    assert r["tout_mesure_et_vert"] is False


def test_tout_mesure_et_vert_exige_qu_AUCUN_gate_ne_soit_inconnu():
    """« SAFE » ne peut pas se dire tant qu'il reste un « je ne sais pas »."""
    assert resume(_gates_ok())["tout_mesure_et_vert"] is True
    assert resume(_gates_ok(sante_des_sources=None))["tout_mesure_et_vert"] is False


@pytest.mark.parametrize("nom", ["mainnet interdit", "testnet verrouille", "mode paper",
                                 "kill switch"])
def test_les_4_gates_de_securite_DURE_sont_toujours_presents(nom: str):
    """Un panneau de securite dont un gate DISPARAIT est aussi dangereux qu'un gate qui ment."""
    assert any(g.name == nom for g in _gates_ok())
