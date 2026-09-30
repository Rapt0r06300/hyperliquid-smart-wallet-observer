"""Carry — le PLANCHER de levier à 1x/1.5x DÉBLOQUE les coins volatils (plus d'opportunités, SANS
plus de risque). HYPE (pire-hausse ~29% stressée à 43.5%) est liquidé à >=2x mais VIABLE à 1x/1.5x.
Anti-régression : si le plancher remonte à 2x, ce test casse (on reperdrait les opportunités)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ecrire_carry", ROOT / "tools" / "ecrire_carry_spot_inputs.py")
_feeder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_feeder)

# Params HYPE réels : funding 0.125 bps/h, spot liq 278k$, pire-hausse 29% -> stressée x1.5 = 43.5%
FUNDING, BASE, LIQ, LEVIER_MAX = 0.125, 0.0, 278_000.0, 10.0
PIRE_STRESSE = 0.29 * 1.5


def _viable(lev: float) -> bool:
    return evaluer_carry_neutre(coin="HYPE", funding_bps_h=FUNDING, base_bps=BASE,
                                liquidite_spot_usd=LIQ, maker=True, levier_max=LEVIER_MAX,
                                marge_ratio=1.0 / lev, pire_hausse_observee=PIRE_STRESSE).viable


def test_hype_liquide_a_2x_mais_viable_a_1x():
    assert _viable(2.0) is False        # à 2x la jambe perp saute -> exclu (ancien comportement)
    assert _viable(1.5) is True         # à 1.5x elle survit et le carry paie
    assert _viable(1.0) is True         # à 1x aussi -> une opportunité RÉELLE, sûre


def test_le_plancher_de_levier_inclut_1x_et_1_5x():
    # regression guard : le scan DOIT essayer 1x et 1.5x, sinon les coins volatils restent exclus
    assert 1.0 in _feeder.LEVIERS_A_ESSAYER
    assert 1.5 in _feeder.LEVIERS_A_ESSAYER


def test_meilleur_levier_debloque_HYPE():
    # avec le plancher corrigé, _meilleur_levier trouve un levier SÛR (<=1.5x) pour HYPE
    best = _feeder._meilleur_levier("HYPE", FUNDING, BASE, LIQ, LEVIER_MAX, 0.29)
    assert best is not None, "HYPE devrait être débloqué à bas levier (plus d'opportunités)"
    lev, mr, v = best
    assert lev <= 1.5 and v.viable
