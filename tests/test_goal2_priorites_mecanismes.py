"""La priorisation est déterministe, n'invente aucun effet favorable et suit p, V et F."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import goal2_priorites_mecanismes as P  # noqa: E402


def test_un_effet_tres_negatif_a_un_p_proche_de_zero() -> None:
    m = P.Mecanisme("x", "a -> b", "t", -100.0, (-150.0, -50.0), 1.0, "REJECTED")
    assert P.score(m)["p_net_positif"] < 0.001


def test_sans_effet_mesure_il_faut_un_statut_explicite() -> None:
    with pytest.raises(ValueError):
        P.score(P.Mecanisme("x", "a -> b", "t", None, None, 1.0, "REJECTED"))


def test_faisabilite_nulle_donne_une_priorite_nulle_et_classement_stable() -> None:
    assert P.score(P.Mecanisme("x", "a -> b", "t", None, None, 0.0, "UNMEASURABLE", 0.5))["priorite"] == 0.0
    assert P.classement() == P.classement() and len({s["code"] for s in P.classement()}) == len(P.MECANISMES) >= 12


def test_chaque_mecanisme_reel_a_une_fiche_complete_et_un_payeur() -> None:
    for s in P.classement():
        assert "NON_RENSEIGNE" not in (s["capacite_100_usd"], s["fill_utile"], s["test_de_refutation"]), s["code"]
        assert "->" in s["transfert"], s["code"]

