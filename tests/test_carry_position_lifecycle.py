"""Tests de l'ETAPE 2 du carry : ouvrir / accruer / sortir / PnL realise + ledger.

Rien n'echappe aux tests (regle 11/07). On verifie le SIGNE (short encaisse), les frais NON
doubles, les 3 sorties (funding, liquidation via re-eval, age), et que LIVE/TEST ne se melangent pas.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_position_lifecycle import (
    MARGE_USD, COUT_SORTIE_2_JAMBES_BPS, MODE_LIVE, MODES_VALIDES,
    SORTIE_FUNDING, SORTIE_LIQUIDATION, SORTIE_AGE,
    ouvrir_position, accruer, raison_de_sortie, pnl_realise, GestionnaireCarry,
)

H = 3_600_000  # 1h en ms


def _decision(viable=True, **kw):
    d = {"coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
         "liquidite_spot_usd": 200_000.0, "cout_entree_bps": 9.0,
         "heures_pour_rentabiliser": 72.0, "viable": viable, "motif": "CARRY_NEUTRE_VIABLE",
         "real_execution": False}
    d.update(kw)
    return d


def _inputs(**kw):
    d = {"ts_ms": 1_000_000, "coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
         "liquidite_spot_usd": 200_000.0, "maker": True, "levier_max": 10.0,
         "marge_ratio": 0.5, "pire_hausse_observee": 0.29, "levier_utilise": 2.0, "perp_px": 40.0}
    d.update(kw)
    return d


# ---------- ouverture ----------

def test_ouvre_sur_viable_notional_marge_x_levier():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    assert pos is not None
    assert pos["coin"] == "HYPE"
    assert pos["notional_usdt"] == pytest.approx(MARGE_USD * 2.0)  # 50 x 2 = 100
    assert pos["marge_usdt"] == pytest.approx(MARGE_USD)
    assert pos["mode"] == MODE_LIVE
    assert pos["real_execution"] is False


def test_pas_d_ouverture_si_refus():
    assert ouvrir_position(_decision(viable=False), _inputs(), now_ms=0) is None


def test_mode_invalide_leve():
    with pytest.raises(ValueError):
        ouvrir_position(_decision(), _inputs(), now_ms=0, mode="MAINNET")


def test_les_deux_jambes_sont_equilibrees_delta_neutre():
    pos = ouvrir_position(_decision(), _inputs(levier_utilise=5.0), now_ms=0)
    # long spot == short perp -> exposition nette nulle (le prix s'annule)
    assert pos["notional_usdt"] == pytest.approx(MARGE_USD * 5.0)


# ---------- accrual : le SHORT encaisse quand funding > 0 ----------

def test_accrual_short_encaisse_positif():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    pos2, add = accruer(pos, now_ms=24 * H, funding_bps_h_courant=0.125)
    assert add > 0.0                                   # short RECOIT
    assert add == pytest.approx(0.125 / 1e4 * pos["notional_usdt"] * 24.0)
    assert pos2["funding_accrued_usdt"] == pytest.approx(add)
    assert pos2["last_accrual_ts_ms"] == 24 * H


def test_accrual_funding_negatif_le_short_paie():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    _, add = accruer(pos, now_ms=10 * H, funding_bps_h_courant=-0.10)
    assert add < 0.0                                   # funding<0 -> le short PAIE


def test_accrual_zero_duree_rien():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=5 * H)
    _, add = accruer(pos, now_ms=5 * H, funding_bps_h_courant=0.125)
    assert add == 0.0


# ---------- frais NON doubles ----------

def test_pnl_realise_frais_non_doubles():
    pos = ouvrir_position(_decision(cout_entree_bps=9.0), _inputs(), now_ms=0)
    pos, _ = accruer(pos, now_ms=100 * H, funding_bps_h_courant=0.125)
    n = pos["notional_usdt"]
    attendu = round(pos["funding_accrued_usdt"] - n * 9.0 / 1e4 - n * COUT_SORTIE_2_JAMBES_BPS / 1e4, 6)
    assert pnl_realise(pos) == pytest.approx(attendu)


def test_pnl_devient_positif_apres_le_break_even():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    pos, _ = accruer(pos, now_ms=1 * H, funding_bps_h_courant=0.125)
    assert pnl_realise(pos) < 0.0                       # 1h : les frais dominent
    pos, _ = accruer(pos, now_ms=5000 * H, funding_bps_h_courant=0.125)
    assert pnl_realise(pos) > 0.0                       # tres longtemps : le funding depasse les frais


# ---------- sorties ----------

def test_sortie_funding_non_rentable():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    assert raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.0) == SORTIE_FUNDING


def test_sortie_liquidation_via_reeval():
    # funding>0 (pas de sortie funding) mais une hausse ENORME -> la jambe perp aurait saute
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    motif = raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.125, hausse_depuis_entree=0.80)
    assert motif == SORTIE_LIQUIDATION


def test_on_garde_quand_tout_va_bien():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    assert raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.125, hausse_depuis_entree=0.0) is None


def test_tick_prix_live_declenche_la_liquidation():
    # entree a 40 ; funding>0 et dans la fenetre d'age, MAIS le perp bondit de +80% -> le short
    # aurait saute. Le suivi prix LIVE doit fermer sans attendre funding<=0/age.
    g = GestionnaireCarry()
    g.tick(_decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)         # entry_perp_px = 40
    e = g.tick(_decision(), _inputs(), now_ms=H, funding_bps_h_courant=0.125, prix_courant=40.0 * 1.8)
    assert e["ferme"] == SORTIE_LIQUIDATION


def test_tick_prix_live_stable_on_garde():
    g = GestionnaireCarry()
    g.tick(_decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    e = g.tick(_decision(), _inputs(), now_ms=H, funding_bps_h_courant=0.125, prix_courant=40.2)  # +0.5%
    assert e["ferme"] is None                                                     # rien d'anormal -> on garde


def test_sortie_age_max():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    assert raison_de_sortie(pos, now_ms=100 * H, funding_bps_h_courant=0.125,
                            hausse_depuis_entree=0.0, age_max_h=50.0) == SORTIE_AGE


# ---------- GestionnaireCarry : OPEN puis CLOSE dans le ledger ----------

def test_gestionnaire_ouvre_puis_ferme_et_ledger_converge():
    g = GestionnaireCarry(mode=MODE_LIVE)
    # t0 : viable -> OPEN
    e0 = g.tick(_decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    assert e0["ouvert"] is True
    assert len(g.ouvertes) == 1
    # t1 : toujours viable, on accrue, pas de re-ouverture (un coin = une position)
    e1 = g.tick(_decision(), _inputs(), now_ms=200 * H, funding_bps_h_courant=0.125)
    assert e1["ouvert"] is False
    assert e1["funding_add_usdt"] > 0.0
    assert len(g.ouvertes) == 1
    # t2 : funding tombe a 0 -> CLOSE avec PnL realise
    e2 = g.tick(_decision(), _inputs(), now_ms=201 * H, funding_bps_h_courant=0.0)
    assert e2["ferme"] == SORTIE_FUNDING
    assert e2["pnl_realise_usdt"] is not None
    assert len(g.ouvertes) == 0
    # le ledger : un OPEN, un CLOSE ; le PnL realise du CLOSE = somme du summary
    rows = g.journal.rows()
    kinds = [r["kind"] for r in rows]
    assert kinds == ["OPEN", "CLOSE"]
    assert g.journal.summary()["realized_net_pnl_usdc"] == pytest.approx(e2["pnl_realise_usdt"])


def test_gestionnaire_n_ouvre_pas_sur_refus():
    g = GestionnaireCarry()
    e = g.tick(_decision(viable=False), _inputs(), now_ms=0)
    assert e["ouvert"] is False
    assert g.journal.rows() == []


def test_gestionnaire_mode_invalide_leve():
    with pytest.raises(ValueError):
        GestionnaireCarry(mode="MAINNET")


def test_live_et_test_ne_se_melangent_pas():
    live = GestionnaireCarry(mode="LIVE")
    fixture = GestionnaireCarry(mode="TEST_FIXTURE")
    live.tick(_decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    fixture.tick(_decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    # deux ledgers distincts, deux modes distincts -> jamais additionnes
    assert live.resume()["mode"] == "LIVE"
    assert fixture.resume()["mode"] == "TEST_FIXTURE"
    assert live.journal is not fixture.journal
    for p in live.ouvertes.values():
        assert p["mode"] == "LIVE"
    for p in fixture.ouvertes.values():
        assert p["mode"] == "TEST_FIXTURE"
