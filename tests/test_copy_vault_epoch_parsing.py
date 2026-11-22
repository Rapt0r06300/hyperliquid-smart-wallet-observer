"""Lecture stricte des horodatages d'époque : refuser plutôt qu'arrondir.

Ces quatre fonctions ont été extraites de `copy_vault_book_loader.py` le 17/11/2026 pour
tenir le plafond de 800 lignes. Elles décident si un carnet du coffre est daté de façon
exploitable — donc si un épisode est causalement lisible. Une seconde d'écart décale la
frontière entre « observé avant la décision » et « observé après » : c'est exactement là
que se fabrique un faux PnL.

Ce que ces tests verrouillent, cas par cas :

* un flottant n'est JAMAIS accepté comme seconde d'époque (0.1 s ne se représente pas en
  binaire : l'accepter introduirait une dérive invisible) ;
* la conversion secondes → millisecondes tronque vers le BAS (`ROUND_FLOOR`), jamais vers
  l'avant — arrondir vers l'avant ferait lire une donnée comme postérieure à ce qu'elle est ;
* un booléen n'est pas un entier, bien que Python le prétende (`True == 1`) ;
* un horodatage hors plage lève ou rend zéro, selon le contrat de chaque fonction, mais
  jamais une valeur « proche ».
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_epoch_parsing import (  # noqa: E402
    _epoch_seconds_to_ms,
    _exact_non_negative_int,
    _optional_epoch_ms,
    _required_epoch_ms,
)
from hl_observer.paper_trading.execution_truth import MAX_SUPPORTED_EPOCH_MS  # noqa: E402


# --------------------------------------------------- secondes -> millisecondes
def test_les_secondes_entieres_deviennent_des_millisecondes_exactes():
    assert _epoch_seconds_to_ms(1_700_000_000) == 1_700_000_000_000


def test_la_troncature_va_vers_le_BAS_jamais_vers_l_avant():
    """Arrondir vers l'avant ferait lire une donnée comme postérieure à ce qu'elle est."""
    assert _epoch_seconds_to_ms(Decimal("1700000000.0009")) == 1_700_000_000_000
    assert _epoch_seconds_to_ms(Decimal("1700000000.9999")) == 1_700_000_000_999


def test_un_flottant_est_refuse_meme_s_il_a_l_air_juste():
    """0.1 s ne se represente pas en binaire : l'accepter serait une derive invisible."""
    with pytest.raises(ValueError, match="JSON number"):
        _epoch_seconds_to_ms(1_700_000_000.0)


def test_une_chaine_ou_un_None_est_refuse():
    for valeur in ("1700000000", None, [], {}):
        with pytest.raises(ValueError):
            _epoch_seconds_to_ms(valeur)


def test_les_secondes_hors_plage_sont_refusees_et_non_bornees():
    for valeur in (0, -1, MAX_SUPPORTED_EPOCH_MS):
        with pytest.raises(ValueError, match="supported UTC range|millisecond resolution"):
            _epoch_seconds_to_ms(valeur)


def test_une_duree_sous_la_milliseconde_est_refusee():
    """Sous la resolution, la troncature donnerait zero : un zero n'est pas une date."""
    with pytest.raises(ValueError):
        _epoch_seconds_to_ms(Decimal("0.0004"))


# --------------------------------------------------- millisecondes obligatoires
def test_une_milliseconde_obligatoire_doit_etre_un_entier_dans_la_plage():
    assert _required_epoch_ms(1_700_000_000_000, "ts") == 1_700_000_000_000
    for mauvais in (0, -1, 1.0, "1", None, MAX_SUPPORTED_EPOCH_MS + 1):
        with pytest.raises(ValueError, match="ts"):
            _required_epoch_ms(mauvais, "ts")


def test_le_nom_du_champ_apparait_dans_le_refus():
    """Un refus sans le nom du champ oblige a chercher : il doit se lire seul."""
    with pytest.raises(ValueError, match="exchange_ts"):
        _required_epoch_ms(None, "exchange_ts")


# --------------------------------------------------- entiers exacts et optionnels
def test_un_booleen_n_est_pas_un_entier_malgre_python():
    """`True == 1` en Python : sans cette garde, un drapeau passerait pour un compteur."""
    assert _exact_non_negative_int(True) is None
    assert _exact_non_negative_int(False) is None
    assert _exact_non_negative_int(0) == 0
    assert _exact_non_negative_int(7) == 7


def test_un_entier_negatif_ou_un_flottant_n_est_pas_exact():
    for valeur in (-1, 1.0, Decimal(3), "3", None):
        assert _exact_non_negative_int(valeur) is None


def test_un_horodatage_optionnel_absent_vaut_zero_et_non_une_erreur():
    """Ici le contrat est l'inverse : l'absence est permise, l'approximation non."""
    assert _optional_epoch_ms(0) == 0
    assert _optional_epoch_ms(1_700_000_000_000) == 1_700_000_000_000
    for absent in (None, "1700000000000", 1.0, True, -1, MAX_SUPPORTED_EPOCH_MS + 1):
        assert _optional_epoch_ms(absent) == 0
