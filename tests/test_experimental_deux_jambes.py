"""AUDIT DEUX JAMBES du carry cross-venue EXPERIMENTAL_PAPER.

Les assertions de frais suivent les constantes de production : le fallback Hyperliquid tier-0 est
conservateur (4.5 bps), jamais l'ancien 3.5 bps optimiste.
"""

from __future__ import annotations

import pytest

from hl_observer.arbitrage.cross_venue_contract import BUY_HL_SELL_BINANCE, SELL_HL_BUY_BINANCE
from hl_observer.experimental.carry_deux_jambes import (
    FRAIS_TAKER_BIN_BPS,
    FRAIS_TAKER_HL_BPS,
    construire_jambes,
    decomposer,
)
from hl_observer.experimental.runner import _raison_sortie_carry

CARNET = {
    "hl_bid": 100.0,
    "hl_ask": 100.1,
    "bin_bid": 99.95,
    "bin_ask": 100.05,
    "hl_demi_spread_bps": 1.0,
    "bin_demi_spread_bps": 1.0,
    "taille_min_usd": 200.0,
    "collecte_ts": 1000.0,
}
H = 3_600_000.0


def test_deux_jambes_venues_sens_prix_hedge_frais_separes():
    a = construire_jambes("X", BUY_HL_SELL_BINANCE, notional=100.0, carnet=CARNET)
    hl, bn = a["jambes"]["hl"], a["jambes"]["bin"]
    assert hl["venue"] == "HL" and hl["sens_txt"] == "LONG" and hl["prix_exec"] == 100.1
    assert bn["venue"] == "BINANCE" and bn["sens_txt"] == "SHORT" and bn["prix_exec"] == 99.95
    assert a["hedge_ratio"] == 1.0 and a["liquidite_ok"] is True
    assert hl["frais_bps"] == FRAIS_TAKER_HL_BPS
    assert bn["frais_bps"] == FRAIS_TAKER_BIN_BPS
    assert hl["slippage_bps"] == 0.0
    assert a["frais_entree_reels_bps"] == 2.0 + FRAIS_TAKER_HL_BPS + FRAIS_TAKER_BIN_BPS


def test_deux_jambes_direction_inverse_vend_hl_et_achete_binance():
    a = construire_jambes("X", SELL_HL_BUY_BINANCE, notional=100.0, carnet=CARNET)
    hl, bn = a["jambes"]["hl"], a["jambes"]["bin"]
    assert hl["sens_txt"] == "SHORT" and hl["prix_exec"] == 100.0
    assert bn["sens_txt"] == "LONG" and bn["prix_exec"] == 100.05


def test_entier_ambigu_refuse():
    with pytest.raises(TypeError, match="CrossVenueDirection"):
        construire_jambes("X", 1, notional=100.0, carnet=CARNET)  # type: ignore[arg-type]


def test_liquidite_insuffisante_et_slippage_quand_notional_depasse_la_profondeur():
    b = construire_jambes("X", BUY_HL_SELL_BINANCE, notional=1000.0, carnet=CARNET)
    assert b["liquidite_ok"] is False and b["jambes"]["hl"]["slippage_bps"] > 0
    assert b["frais_entree_reels_bps"] > 9.0


def test_decomposition_settled_vs_accru_basis_et_liquidable():
    pos = {
        "coin": "X", "notional_usd": 100.0, "sens": 1, "d_bps_h": 1.0,
        "ts_ouverture_ms": 0, "base_entree_bps": 0.0, "hold_h": 168.0,
        "cout_entree_bps": 5.0, "meta": {"cout_ar_bps": 10.0},
    }
    d = decomposer(pos, carnet_courant=CARNET, d_courant=1.0, base_courant_bps=0.0, now_ms=2.5 * H)
    assert d["heures_settled"] == 2
    assert d["funding_settled_usd"] == 0.02 and d["funding_accru_estime_usd"] == 0.005
    assert d["pnl_basis_usd"] == 0.0
    expected_entry_cost = (2.0 + FRAIS_TAKER_HL_BPS + FRAIS_TAKER_BIN_BPS) / 1e4 * 100.0
    assert d["frais_entree_payes_usd"] == pytest.approx(expected_entry_cost)
    assert d["liquidite_ok"] is True
    assert d["pnl_liquidable_maintenant_usd"] == pytest.approx(0.02 - 2 * expected_entry_cost)


def test_decomposition_basis_est_symetrique_par_direction():
    base = {"coin": "X", "notional_usd": 100.0, "d_bps_h": 0.0, "ts_ouverture_ms": 0,
            "base_entree_bps": 0.0, "cout_entree_bps": 0.0, "meta": {}}
    long_hl = decomposer({**base, "sens": 1}, carnet_courant=None, d_courant=0.0,
                         base_courant_bps=10.0, now_ms=0.0)
    short_hl = decomposer({**base, "sens": -1}, carnet_courant=None, d_courant=0.0,
                          base_courant_bps=-10.0, now_ms=0.0)
    assert long_hl["pnl_basis_usd"] == pytest.approx(0.1)
    assert short_hl["pnl_basis_usd"] == pytest.approx(0.1)


def test_les_6_sorties_automatiques():
    p = {"coin": "X", "notional_usd": 100.0, "sens": 1, "d_bps_h": 1.0,
         "base_entree_bps": 0.0, "hold_h": 168.0, "meta": {"cout_ar_bps": 10.0}}
    now = 1_000_000.0
    ok = {"collecte_ts": now / 1000.0, "taille_min_usd": 1000.0}
    assert _raison_sortie_carry(p, {"d_bps_h": -1.0, "base_bps": 0.0}, ok, now_ms=now, age_h=1.0) == "FUNDING_FLIP"
    assert _raison_sortie_carry(p, {"d_bps_h": 1.0, "base_bps": 0.0},
                                {"collecte_ts": now / 1000.0, "taille_min_usd": 10.0},
                                now_ms=now, age_h=1.0) == "LIQUIDITE_INSUFFISANTE"
    assert _raison_sortie_carry(p, {"d_bps_h": 1.0, "base_bps": 0.0},
                                {"collecte_ts": now / 1000.0 - 9999, "taille_min_usd": 1000.0},
                                now_ms=now, age_h=1.0) == "QUOTE_PERIMEE"
    assert _raison_sortie_carry(p, {"d_bps_h": 1.0, "base_bps": -50.0}, ok, now_ms=now, age_h=1.0) == "BASIS_ADVERSE"
    assert _raison_sortie_carry(p, {"d_bps_h": 1.0, "base_bps": 0.0}, ok, now_ms=now, age_h=200.0) == "HOLD_ATTEINT"
    assert _raison_sortie_carry(p, {"d_bps_h": 1.0, "base_bps": 0.0}, ok, now_ms=now, age_h=1.0) is None
