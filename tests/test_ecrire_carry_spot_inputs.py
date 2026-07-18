"""Tests de l'outil de mesure carry (tools/ecrire_carry_spot_inputs.py) : carnet REEL + VWAP + plancher.
Rien n'echappe aux tests, meme un tool. Le reseau (_post) est monkeypatche -> 100% offline."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("ecrire_carry_tool", ROOT / "tools" / "ecrire_carry_spot_inputs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_vwap_achat_est_au_dessus_du_mid_slippage_reel():
    m = _load()
    # bid 39.9 ; asks 40.0 x5 (=200$) puis 40.5 (large). Acheter 500$ traverse les 2 niveaux.
    m._post = lambda payload, **k: {"levels": [
        [{"px": "39.9", "sz": "10"}],
        [{"px": "40.0", "sz": "5"}, {"px": "40.5", "sz": "100"}]]}
    mid, prof, vwap = m._carnet_spot("@T", notional_cible=500.0)
    assert mid == 39.95
    assert vwap > mid                                        # acheter POUSSE le prix au-dessus du mid
    assert abs(vwap - 500.0 / (200 / 40.0 + 300 / 40.5)) < 1e-6   # VWAP exact
    assert prof > 500.0                                      # profondeur reelle mesuree


def test_carnet_vide_retourne_none():
    m = _load()
    m._post = lambda payload, **k: {"levels": [[], []]}
    assert m._carnet_spot("@T", notional_cible=500.0) is None


def test_profondeur_bornee_par_l_impact_max():
    m = _load()
    # 2e niveau au-dela de +2% d'impact -> ignore dans la profondeur ET le VWAP
    m._post = lambda payload, **k: {"levels": [
        [{"px": "100.0", "sz": "1"}],
        [{"px": "100.0", "sz": "3"}, {"px": "110.0", "sz": "100"}]]}
    mid, prof, vwap = m._carnet_spot("@T", impact_max=0.02, notional_cible=500.0)
    assert prof == 300.0                                     # seul le niveau a 100.0 compte (110 > +2%)


def test_plancher_liquidite_est_principiel():
    m = _load()
    assert m.NOTIONNEL_MAX_USD == 500.0
    assert m.SECURITE_PROFONDEUR == 5.0
    assert m.LIQUIDITE_MIN_USD == m.NOTIONNEL_MAX_USD * m.SECURITE_PROFONDEUR == 2500.0
