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


# ---------- A2 : classement transversal net (top-K) ----------

def test_classer_viables_par_carry_net_et_top_k():
    m = _load()
    viables = [
        ("A", {"coin": "A"}, 10.0, 2.0),   # net 2
        ("B", {"coin": "B"}, 5.0, 9.0),    # net 9 (meilleur)
        ("C", {"coin": "C"}, 1.0, 5.0),    # net 5
        ("D", {"coin": "D"}, 50.0, 1.0),   # net 1
    ]
    r = m.classer_viables(viables, top_k=2)
    assert [x[0] for x in r] == ["B", "C"]           # top-2 par carry NET


def test_classer_viables_tie_break_break_even_court():
    m = _load()
    viables = [("A", {}, 20.0, 3.0), ("B", {}, 8.0, 3.0)]   # meme net -> break-even court d'abord
    assert [x[0] for x in m.classer_viables(viables, top_k=2)] == ["B", "A"]


def test_classer_viables_gain_none_est_relegue():
    m = _load()
    viables = [("A", {}, 10.0, None), ("B", {}, 10.0, 0.1)]
    assert m.classer_viables(viables, top_k=2)[0][0] == "B"   # net inconnu -> en dernier


def test_plafond_shortlist_est_defini():
    m = _load()
    assert isinstance(m.PLAFOND_SHORTLIST, int) and m.PLAFOND_SHORTLIST >= 1


# ---------- A3 : levier en risk-parity (tampon liq uniforme) ----------

def test_a3_plus_de_securite_baisse_ou_egale_le_levier():
    m = _load()
    b1 = m._meilleur_levier("X", 1.0, 0.0, 200_000.0, 10.0, 0.15, securite=1.0)
    b15 = m._meilleur_levier("X", 1.0, 0.0, 200_000.0, 10.0, 0.15, securite=1.5)
    assert b1 is not None and b15 is not None
    assert b15[0] <= b1[0]                    # plus de securite -> levier <= (plus conservateur)


def test_a3_coin_volatil_recoit_moins_de_levier_risk_parity():
    m = _load()
    calme = m._meilleur_levier("CALM", 1.0, 0.0, 200_000.0, 10.0, 0.06)    # pire 6%
    volatil = m._meilleur_levier("VOL", 1.0, 0.0, 200_000.0, 10.0, 0.35)   # pire 35%
    assert calme is not None
    lev_vol = volatil[0] if volatil else 0.0
    assert lev_vol <= calme[0]                # risk-parity : le volatil a MOINS de levier (ou refuse)


def test_securite_liquidation_est_definie_et_conservative():
    m = _load()
    assert m.SECURITE_LIQUIDATION >= 1.0
