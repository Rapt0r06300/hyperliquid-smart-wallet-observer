"""JUGE SIGNÉ DU CARRY CROSS-VENUE (23/07, nouveau cap). On prouve : le juge distingue un carry PROPRE
(les 2 jambes paient, base minuscule, persistant, net>0 IN+OOS) d'un PIÈGE (base qui dérive, jambe
figée, coût inconnu), là où la médiane-poolée de l'ancien juge était noyée par les majors au plancher.
"""
from __future__ import annotations

from hl_observer.funding.cross_venue_carry_judge import juger_coin, charger_series


def _serie(n=400, hl_px=100.0, bin_px=100.0, hl_f=0.125, bin_f_base=-0.10, bin_fige=False):
    out = []
    for i in range(n):
        bf = bin_f_base if bin_fige else bin_f_base + (i % 3) * 0.001   # varie -> jambe réelle
        out.append((float(i), hl_px, bin_px, hl_f, bf))
    return out


def test_un_carry_propre_est_SURVIVANT_OOS():
    # d = 0.125 − (~-0.099) ≈ +0.224 bph, persistant, base 0 ; net@168 = 0.224×168 − (6+6.6) ≈ +25 bps
    r = juger_coin(_serie(), cout_ar_bps=6.0)
    assert r["verdict"] == "SURVIVANT_OOS"
    assert r["net_hold_bps"] > 0 and r["oos_net_hold_bps"] > 0 and r["persist"] >= 0.9


def test_une_jambe_binance_figee_est_ecartee():
    assert juger_coin(_serie(bin_fige=True), cout_ar_bps=6.0)["verdict"] == "JAMBE_FIGEE"


def test_une_base_qui_derive_est_BASE_SUSPECTE():
    # hl_px 100.3 vs bin_px 100.0 -> base ~30 bps > plafond 15 : instrument mal jumelé
    assert juger_coin(_serie(hl_px=100.3), cout_ar_bps=6.0)["verdict"] == "BASE_SUSPECTE"


def test_sans_carnet_le_verdict_est_COUT_INCONNU_pas_une_promesse():
    r = juger_coin(_serie(), cout_ar_bps=None)
    assert r["verdict"] == "COUT_INCONNU" and r["net_hold_bps"] is None
    assert r["apr_pct"] > 0                              # mesuré (brut), mais NON promu


def test_serie_trop_courte_est_INSUFFISANT():
    assert juger_coin(_serie(n=10), cout_ar_bps=6.0)["verdict"] == "INSUFFISANT"


def test_charger_survit_a_l_absence(tmp_path):
    assert charger_series(tmp_path) == {}
