"""Tests de l'ETAPE 2 du carry : ouvrir / accruer / sortir / PnL realise + ledger.

Rien n'echappe aux tests (regle 11/07). On verifie le SIGNE (short encaisse), les frais NON
doubles, les 3 sorties (funding, liquidation via re-eval, age), et que LIVE/TEST ne se melangent pas.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_position_lifecycle import (
    MARGE_USD, COUT_SORTIE_2_JAMBES_BPS, MODE_LIVE, MODES_VALIDES,
    SORTIE_FUNDING, SORTIE_LIQUIDATION, SORTIE_AGE, SORTIE_BASE_CONVERGEE,
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
    # t2 : funding en HEMORRAGIE (-1,0 <= seuil -0,5) -> CLOSE immediat (A6: un simple 0.0 est tolere)
    e2 = g.tick(_decision(), _inputs(), now_ms=201 * H, funding_bps_h_courant=-1.0)
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


# ---------- A5 : convergence de base (2e PnL) ----------

def test_a5_defaut_base_zero_ne_change_pas_le_pnl():
    pos = ouvrir_position(_decision(), _inputs(), now_ms=0)
    pos, _ = accruer(pos, now_ms=100 * H, funding_bps_h_courant=0.125)
    assert pnl_realise(pos) == pnl_realise(pos, base_bps_courant=0.0)   # defaut = 0 -> inchange (compat)


def test_a5_pnl_retire_la_base_residuelle_non_capturee():
    pos = ouvrir_position(_decision(base_bps=10.0), _inputs(), now_ms=0)
    pos, _ = accruer(pos, now_ms=100 * H, funding_bps_h_courant=0.125)
    n = pos["notional_usdt"]
    p_convergee = pnl_realise(pos, base_bps_courant=0.0)     # base capturee -> pas de correction
    p_residuelle = pnl_realise(pos, base_bps_courant=10.0)   # base pas capturee -> retire 10 bps
    assert p_residuelle == pytest.approx(p_convergee - 10.0 * n / 1e4)


def test_a5_sortie_quand_la_base_a_converge():
    # 🔴 MIS A JOUR (nuit 19-20/07) : base 10 -> capture 9 bps < ~11 bps de couts TOTAUX ->
    # fermer REALISAIT une perte (-0,08 $ observe en vrai, puis reouverture 1 min apres).
    # A5 x A4 : on ne verrouille que si le PnL realise est POSITIF. Base 30 -> capture 29 bps
    # > couts -> la, on verrouille.
    # cout COHERENT avec la base (le modele credite la base a l'entree) : 11 - 30 = -19
    pos = ouvrir_position(_decision(base_bps=30.0, cout_entree_bps=-19.0), _inputs(), now_ms=0)
    assert raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.125,
                            base_bps_courant=1.0) == SORTIE_BASE_CONVERGEE


def test_a5_base_pas_encore_convergee_on_garde():
    pos = ouvrir_position(_decision(base_bps=10.0), _inputs(), now_ms=0)
    assert raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.125, base_bps_courant=9.0) is None


def test_a5_base_negligeable_pas_de_sortie_convergence():
    pos = ouvrir_position(_decision(base_bps=-0.68), _inputs(), now_ms=0)   # base < min -> rien a verrouiller
    assert raison_de_sortie(pos, now_ms=H, funding_bps_h_courant=0.125, base_bps_courant=0.0) is None


def test_a5_gestionnaire_ferme_et_realise_sur_convergence():
    g = GestionnaireCarry()
    g.tick(_decision(base_bps=30.0, cout_entree_bps=-19.0), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    e = g.tick(_decision(base_bps=30.0, cout_entree_bps=-19.0), _inputs(), now_ms=H, funding_bps_h_courant=0.125,
               base_bps_courant=0.5)
    assert e["ferme"] == SORTIE_BASE_CONVERGEE and e["pnl_realise_usdt"] is not None
    assert e["pnl_realise_usdt"] > 0, "une capture verrouillee doit etre GAGNANTE (A5 x A4)"


def test_NUIT_1920_une_capture_de_base_PERDANTE_ne_ferme_pas():
    """🔴 A5 x A4 : cette nuit, 2 'captures' ont REALISE -0,08 $ et -0,07 $ (motif 'CAPTURE' !)
    puis rouvert 1 min apres. Une capture qui ne paie pas sa propre sortie est un churn deguise.
    Desormais SORTIE_BASE_CONVERGEE n'est rendue que si le PnL realise serait POSITIF."""
    from hl_observer.funding.carry_position_lifecycle import raison_de_sortie, pnl_realise

    # position jeune : quasi aucun funding accru, base d'entree 2 bps -> capture < frais de sortie
    pos = {"coin": "PURR", "mode": "LIVE", "notional_usdt": 75.0, "marge_usdt": 50.0,
           "levier": 1.5, "marge_ratio": 0.667, "levier_max": 3.0,
           "entry_ts_ms": 0, "last_accrual_ts_ms": 0, "funding_bps_h_entree": 0.125,
           "cout_entree_bps": 9.0, "base_bps_entree": 2.0, "entry_perp_px": 0.07,
           "liquidite_spot_usd": 15_000.0, "pire_hausse_entree": 0.26,
           "funding_accrued_usdt": 0.0001, "gain_net_24h_bps": 1.6}
    assert pnl_realise(pos, base_bps_courant=0.0) < 0, "fixture : la capture DOIT etre perdante ici"
    motif = raison_de_sortie(pos, now_ms=3_600_000, funding_bps_h_courant=0.125,
                             base_bps_courant=0.0)     # base convergee (2.0 -> 0.0)
    assert motif is None, "capture perdante -> on GARDE (le funding continue de courir)"

    # contre-epreuve : assez de funding accru pour que la capture PAIE -> on verrouille
    pos_riche = dict(pos); pos_riche["funding_accrued_usdt"] = 0.20   # > frais de sortie
    assert pnl_realise(pos_riche, base_bps_courant=0.0) > 0
    assert raison_de_sortie(pos_riche, now_ms=3_600_000, funding_bps_h_courant=0.125,
                            base_bps_courant=0.0) == "BASE_CONVERGEE_PREMIUM_CAPTURE"


# ---------------- 21/07 : « la fermeture des carry ne se fait jamais » ----------------

def test_prise_de_profit_base_ferme_quand_le_net_paie_TOUT_meme_sans_convergence():
    """Le 20/07 a 20h02, +0,31 $ de latent et RIEN pour l'encaisser (A5 exige la convergence
    vers zero). Desormais : profit net >= 0,05 $ (tous couts payes) -> verrouillage."""
    from hl_observer.funding.carry_position_lifecycle import (
        SEUIL_PRISE_PROFIT_USD, SORTIE_PRISE_PROFIT_BASE, pnl_realise, raison_de_sortie)
    # modele A5 : cout_entree_bps = frais reels (5,5) - base creditee a l'entree (30) = -24,5
    p = {"coin": "SOL", "notional_usdt": 150.0, "funding_accrued_usdt": 0.02,
         "cout_entree_bps": -24.5, "base_bps_entree": 30.0, "liquidite_spot_usd": 100000.0,
         "levier_max": 10.0, "marge_ratio": 0.5, "pire_hausse_entree": 0.10,
         "entry_ts_ms": 0}
    # base 30 -> -10 : PAS convergee vers zero (overshoot), mais 40 bps captures sur 150$
    assert pnl_realise(p, base_bps_courant=-10.0) >= SEUIL_PRISE_PROFIT_USD
    motif = raison_de_sortie(p, now_ms=3_600_000, funding_bps_h_courant=0.125,
                             base_bps_courant=-10.0)
    assert motif in (SORTIE_PRISE_PROFIT_BASE, "BASE_CONVERGEE_PREMIUM_CAPTURE"), motif
    # profit sous le seuil -> on GARDE (le funding court, pas de churn)
    assert raison_de_sortie(p, now_ms=3_600_000, funding_bps_h_courant=0.125,
                            base_bps_courant=28.0) is None
