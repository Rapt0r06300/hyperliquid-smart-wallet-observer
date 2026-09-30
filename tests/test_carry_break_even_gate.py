"""PLANCHER DE BREAK-EVEN — calibré sur la MESURE, pas l'intuition.

DÉCOUVERTE (18/07) : le break-even d'un carry HL est ~76-88 h QUEL QUE SOIT le funding courant,
parce que la PRIME décroît vers le plancher protocolaire — seul le plancher (0.125 bps/h) persiste.
Un funding 4× plus haut ne donne que 76 h au lieu de 88 h. Un plancher à 24 h aurait tué TOUS les
carrys. On calibre donc à 120 h : les carrys normaux passent, les ABSURDES (base très négative ->
coût d'entrée énorme) sont écartés. Conséquence honnête : un carry est négatif ~3-4 jours, PUIS monte."""
from __future__ import annotations

import pytest
import importlib.util
from pathlib import Path

from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("feeder", ROOT / "tools" / "ecrire_carry_spot_inputs.py")
_feeder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_feeder)


def _break_even(funding_bps_h: float, base_bps: float = 0.0) -> float | None:
    v = evaluer_carry_neutre(coin="HYPE", funding_bps_h=funding_bps_h, base_bps=base_bps,
                             liquidite_spot_usd=278_000.0, maker=True, levier_max=10.0,
                             marge_ratio=1.0 / 1.5, pire_hausse_observee=0.29 * 1.5)
    return v.heures_pour_rentabiliser


def test_le_plafond_est_DERIVE_de_la_vie_d_une_position_pas_choisi():
    """🔴 REECRIT LE 21/07. L'ancien test gravait 120 h — un nombre choisi. Le plafond est
    desormais DERIVE : la moitie de la vie d'une position (336 h / 2 = 168 h), pour qu'une
    position passe au moins autant de temps a GAGNER qu'a rembourser. Un plafond choisi se
    justifie par une opinion ; un plafond derive se justifie par une contrainte."""
    from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT
    assert _feeder.PLAFOND_COHERENT_H == pytest.approx(
        _feeder._plafond_break_even(AGE_MAX_H_DEFAUT), abs=1.0)
    assert 0 < _feeder.PLAFOND_COHERENT_H < AGE_MAX_H_DEFAUT
    assert _feeder.MAX_BREAK_EVEN_H <= _feeder.PLAFOND_COHERENT_H


def test_la_prime_decroit_le_break_even_reste_long():
    """LA découverte : 4× plus de funding ne divise PAS le break-even par 4 (la prime s'évapore)."""
    be_bas, be_haut = _break_even(0.125), _break_even(0.6)
    assert be_bas is not None and be_haut is not None
    assert be_haut < be_bas                          # un peu mieux...
    assert be_haut > 60.0                            # ...mais toujours ~3 jours, pas 20 h


def test_carry_normal_PASSE_le_plafond():
    """Le break-even inclut la sortie depuis le 21/07 : ~176 h au plancher, pas 88. Il doit
    rester sous le plafond coherent (168 h) UNIQUEMENT si la base aide un peu — sinon un
    carry a base nulle au plancher est, honnetement, a la limite."""
    be = _break_even(0.125, base_bps=3.0)            # base legerement favorable
    assert be is not None and be <= _feeder.MAX_BREAK_EVEN_H


def test_un_carry_a_base_NULLE_au_plancher_PASSE_mais_de_justesse():
    """Chiffre a garder sous les yeux : sans aide de la base, le funding plancher met ~176 h
    a rembourser l'ALLER-RETOUR (7,3 jours), pour une position qui vit 14 jours. Ca passe —
    mais il ne reste que la moitie de la vie pour gagner, et 20 bps nets au total."""
    be = _break_even(0.125, base_bps=0.0)
    assert be is not None
    assert 160 <= be <= 200, be
    assert be <= _feeder.MAX_BREAK_EVEN_H
    from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT
    assert be > AGE_MAX_H_DEFAUT * 0.4, "un carry au plancher n'est JAMAIS rapide, et le dire compte"


def test_carry_ABSURDE_est_ecarte():
    """Base très négative -> on paie la base à l'entrée -> coût énorme -> jamais rembourse."""
    be = _break_even(0.125, base_bps=-60.0)          # coût = 11 + 60 = 71 bps
    assert be is None or be > _feeder.MAX_BREAK_EVEN_H
