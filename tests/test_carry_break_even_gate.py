"""PLANCHER DE BREAK-EVEN — calibré sur la MESURE, pas l'intuition.

DÉCOUVERTE (18/07) : le break-even d'un carry HL est ~76-88 h QUEL QUE SOIT le funding courant,
parce que la PRIME décroît vers le plancher protocolaire — seul le plancher (0.125 bps/h) persiste.
Un funding 4× plus haut ne donne que 76 h au lieu de 88 h. Un plancher à 24 h aurait tué TOUS les
carrys. On calibre donc à 120 h : les carrys normaux passent, les ABSURDES (base très négative ->
coût d'entrée énorme) sont écartés. Conséquence honnête : un carry est négatif ~3-4 jours, PUIS monte."""
from __future__ import annotations

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


def test_plancher_calibre_sur_la_mesure():
    assert _feeder.MAX_BREAK_EVEN_H == 120.0        # pas 24 : la mesure a montré que ça tuerait tout


def test_la_prime_decroit_le_break_even_reste_long():
    """LA découverte : 4× plus de funding ne divise PAS le break-even par 4 (la prime s'évapore)."""
    be_bas, be_haut = _break_even(0.125), _break_even(0.6)
    assert be_bas is not None and be_haut is not None
    assert be_haut < be_bas                          # un peu mieux...
    assert be_haut > 60.0                            # ...mais toujours ~3 jours, pas 20 h


def test_carry_normal_PASSE_le_plancher():
    be = _break_even(0.125)                          # cas réel d'aujourd'hui : ~88 h
    assert be <= _feeder.MAX_BREAK_EVEN_H            # <= 120 -> on l'ouvre (il rembourse en 3-4 j)


def test_carry_ABSURDE_est_ecarte():
    """Base très négative -> on paie la base à l'entrée -> coût énorme -> jamais rembourse."""
    be = _break_even(0.125, base_bps=-60.0)          # coût = 11 + 60 = 71 bps
    assert be is None or be > _feeder.MAX_BREAK_EVEN_H
