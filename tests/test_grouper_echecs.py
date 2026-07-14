"""LE GROUPEUR D'ECHECS DOIT COMPTER LES CAUSES, PAS LES SYMPTOMES (2026-07-12).

Regle du projet : aucun module sans test. Celui-ci defend l'idee centrale de l'outil --
plusieurs tests tues par LA MEME exception forment UNE cause, pas plusieurs.

Aucun reseau, aucun ordre : on parse du texte.
"""
from __future__ import annotations

from tools.grouper_echecs import grouper, normaliser, rapport

# Une vraie sortie pytest, reduite : 3 tests, 2 causes.
_SORTIE = """
=================================== FAILURES ===================================
_____________________________ test_position_ouvre ______________________________
tests/test_ui.py:12: in test_position_ouvre
    assert etat == "SIMULATION_ACTIVE"
E   AssertionError: assert 'OBSERVING_NO_VIRTUAL_ENTRY' == 'SIMULATION_ACTIVE'
_______________________________ test_pnl_visible _______________________________
tests/test_ui.py:20: in test_pnl_visible
    assert etat == "SIMULATION_ACTIVE"
E   AssertionError: assert 'OBSERVING_NO_VIRTUAL_ENTRY' == 'SIMULATION_ACTIVE'
______________________________ test_chemin_marks _______________________________
tests/test_replay.py:8: in test_chemin_marks
    future = [(t, m) for (t, m) in path if t > entry_ts]
E   TypeError: '>' not supported between instances of 'str' and 'float'
=========================== short test summary info ============================
"""


def test_deux_tests_tues_par_la_MEME_exception_forment_UNE_seule_cause() -> None:
    """LE point de l'outil. Sinon on lit "30 echecs" et on croit a 30 bugs."""
    causes = grouper(_SORTIE)

    assert len(causes) == 2, (
        f"3 echecs, 2 exceptions distinctes -> 2 causes. Obtenu : {len(causes)}. "
        "Si le groupeur rend 3 causes, il compte des symptomes et ne sert a rien."
    )
    gros = max(causes.values(), key=len)
    assert sorted(gros) == ["test_pnl_visible", "test_position_ouvre"]


def test_le_bruit_variable_ne_fabrique_pas_de_fausses_causes() -> None:
    """Adresses memoire et chemins DIFFERENT a chaque run : sans normalisation,
    deux echecs identiques auraient l'air d'etre deux causes distinctes."""
    a = normaliser("AssertionError: object at 0x7f0011 in C:\\Users\\flo\\x.py failed")
    b = normaliser("AssertionError: object at 0x9affee in C:\\Users\\flo\\y.py failed")
    assert a == b, (
        "deux fois LA MEME erreur, a une adresse memoire pres, doivent se confondre -- "
        "sinon le rapport annonce autant de causes que d'executions"
    )


def test_une_sortie_sans_echec_ne_declenche_aucune_alarme() -> None:
    """Un outil qui crie sur une suite verte finit ignore."""
    assert grouper("===== 3191 passed in 201s =====") == {}
    assert "Aucun echec" in rapport({})


def test_le_rapport_met_la_PLUS_GROSSE_cause_en_premier() -> None:
    """On repare ce qui fait tomber 21 tests avant ce qui en fait tomber 1."""
    texte = rapport(grouper(_SORTIE))
    pos_grosse = texte.index("OBSERVING_NO_VIRTUAL_ENTRY")
    pos_petite = texte.index("not supported between")
    assert pos_grosse < pos_petite, "la cause a 2 symptomes doit passer avant celle a 1"
    assert "2 CAUSE(S) RACINE(S) pour 3 echec(s)" in texte
