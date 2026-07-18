"""Funding cross-venue — l'arb de dispersion identifie le bon sens et refuse quand ça ne paie pas.
Le prédicteur est marqué NON validé (on teste juste sa cohérence mathématique)."""
from __future__ import annotations

from hl_observer.funding.cross_venue_funding import arb_funding_cross_venue, funding_predit_bps_h


def test_arb_long_ou_funding_bas_short_ou_haut():
    r = arb_funding_cross_venue("BTC", funding_a_bps_h=0.05, funding_b_bps_h=0.30,
                                venue_a="HL", venue_b="Binance", cout_entree_bps=11.0)
    assert r.long_venue == "HL" and r.short_venue == "Binance"   # long où funding bas (HL 0.05)
    assert abs(r.capture_bps_h - 0.25) < 1e-9
    assert r.viable is True                                       # 0.25 bps/h × 720 h ≫ 11 bps


def test_arb_dispersion_trop_faible_refuse():
    r = arb_funding_cross_venue("BTC", 0.125, 0.130, venue_a="HL", venue_b="Bybit", cout_entree_bps=11.0)
    assert r.viable is False and r.motif == "DISPERSION_TROP_FAIBLE"


def test_arb_funding_inconnu_refuse():
    r = arb_funding_cross_venue("BTC", None, 0.30, venue_a="HL", venue_b="Binance", cout_entree_bps=11.0)
    assert r.viable is False and r.motif == "FUNDING_INCONNU_SUR_UNE_VENUE"


def test_predicteur_borne_et_none_si_absent():
    assert funding_predit_bps_h(None) is None
    # prime bornée : une prime énorme ne fait pas exploser la prédiction
    assert funding_predit_bps_h(1000.0) == funding_predit_bps_h(5.0)
    # plancher + prime
    assert funding_predit_bps_h(0.0) == 0.125
