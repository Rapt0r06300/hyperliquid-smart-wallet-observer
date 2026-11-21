"""Une tranche mal formee doit REFUSER en se nommant, jamais lever un IndexError nu.

CE QUE CES TESTS PROTEGENT. Le fuzzing de l'audit a trouve le 2026-11-21 :

    hl_observer.backtesting.copy_vault_identite_campagne.nom_de_campagne([])
        -> IndexError: list index out of range

`nom_de_campagne` fabrique le NOM DU DOSSIER d'une campagne : c'est l'endroit ou s'ecrivent
`TRIALS.jsonl`, `ATTEMPTS.jsonl` et `CHECKPOINT.json`. Une exception nue a cet endroit ne dit
ni ce qui etait invalide ni d'ou ca venait. La regle du projet est un REFUS NOMME : une donnee
contradictoire s'arrete, elle ne produit pas un nom tronque sous lequel des essais iraient
s'ecrire.

Le dernier test est DISCRIMINANT : il prouve que l'ancien code aurait bien echoue, pour qu'un
futur retour en arriere (`int(tranche[0])`) redevienne rouge ici.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_identite_campagne import (
    SEPARATEUR,
    empreinte_de_tranche,
    nom_de_campagne,
    tranche_valide,
)

MAL_FORMEES = ([], [1], (), (1,), 5, "xy", (1, "a"), {"debut": 1}, None.__class__)


def test_le_comportement_normal_est_inchange():
    """La non-regression d'abord : les deux formes legitimes rendent EXACTEMENT l'ancien nom."""
    assert nom_de_campagne("abc", None) == "abc"
    assert nom_de_campagne("abc", (10, 20)) == f"abc{SEPARATEUR}10-20"
    assert empreinte_de_tranche(None) == ""
    e = empreinte_de_tranche((10, 20))
    assert len(e) == 8 and e == empreinte_de_tranche((10, 20))


@pytest.mark.parametrize("mauvaise", MAL_FORMEES)
def test_nom_de_campagne_refuse_en_se_nommant(mauvaise):
    with pytest.raises(ValueError, match="TRANCHE_INVALIDE"):
        nom_de_campagne("abc", mauvaise)


@pytest.mark.parametrize("mauvaise", MAL_FORMEES)
def test_empreinte_de_tranche_refuse_en_se_nommant(mauvaise):
    with pytest.raises(ValueError, match="TRANCHE_INVALIDE"):
        empreinte_de_tranche(mauvaise)


@pytest.mark.parametrize("mauvaise", MAL_FORMEES)
def test_aucune_exception_fatale_ne_fuit(mauvaise):
    """Le fuzzeur de l'audit traite IndexError / ZeroDivisionError / NameError comme un CRASH.

    Un `ValueError` est au contraire la fonction qui SE DEFEND. On verifie la famille, pas
    seulement le message : c'est ce que l'audit mesure.
    """
    with pytest.raises(ValueError) as capture:
        tranche_valide(mauvaise)
    assert not isinstance(capture.value, IndexError)
    assert "TRANCHE_INVALIDE" in str(capture.value)


def test_le_defaut_existait_vraiment_sans_le_validateur():
    """DISCRIMINANT : l'ancienne formule leve bien un IndexError sur une liste vide."""
    tranche: list[int] = []
    with pytest.raises(IndexError):
        f"abc{SEPARATEUR}{int(tranche[0])}-{int(tranche[1])}"
