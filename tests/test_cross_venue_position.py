"""Exploitation cross-venue — ouvrir/accruer/sortir/PnL. Rien d'inventé : capture inconnue = 0 gain
et sortie ; les DEUX coûts (entrée + sortie) sont comptés."""
from __future__ import annotations

from hl_observer.funding.cross_venue_position import (
    accruer, break_even_heures, ouvrir, pnl_realise, raison_de_sortie)

OPP = {"coin": "BTC", "long_venue": "HL", "short_venue": "Binance", "capture_bps_h": 0.25}


def test_ouvrir_refuse_une_opportunite_incomplete():
    assert ouvrir({"coin": "BTC"}, notional_usd=500.0, now_ms=0) is None
    assert ouvrir(OPP, notional_usd=0.0, now_ms=0) is None


def test_ouvrir_et_break_even():
    p = ouvrir(OPP, notional_usd=500.0, now_ms=0)
    assert p["long_venue"] == "HL" and p["short_venue"] == "Binance"
    # (11 entrée + 11 sortie) / 0.25 bps/h = 88 h
    assert break_even_heures(p) == 88.0


def test_accrue_au_taux_COURANT_et_rien_si_inconnu():
    p = ouvrir(OPP, notional_usd=500.0, now_ms=0)
    g = accruer(p, 0.25, now_ms=3_600_000)                 # 1 h à 0.25 bps/h sur 500$
    assert abs(g - 500.0 * 0.25 / 1e4) < 1e-9
    assert accruer(p, None, now_ms=7_200_000) == 0.0       # capture inconnue -> 0 gain inventé


def test_sortie_quand_la_dispersion_disparait():
    p = ouvrir(OPP, notional_usd=500.0, now_ms=0)
    assert raison_de_sortie(p, 0.25, now_ms=3_600_000) is None            # on tient
    assert raison_de_sortie(p, 0.001, now_ms=3_600_000) == "SORTIE_DISPERSION_DISPARUE"
    assert raison_de_sortie(p, None, now_ms=3_600_000) == "SORTIE_CAPTURE_INCONNUE"
    assert raison_de_sortie(p, 0.25, now_ms=400 * 3_600_000) == "SORTIE_AGE"


def test_pnl_compte_les_DEUX_couts():
    p = ouvrir(OPP, notional_usd=500.0, now_ms=0)
    accruer(p, 0.25, now_ms=100 * 3_600_000)               # 100 h -> 1.25$ de funding
    pnl = pnl_realise(p)
    couts = 500.0 * 22.0 / 1e4                              # 11 + 11 bps
    assert abs(pnl - (1.25 - couts)) < 1e-6 and pnl > 0     # rembourse après 88 h
