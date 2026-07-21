"""Tests du RENFORT de position carry (21/07) — grossir sans churn.

Ce que ces tests PROUVENT (pas « exécutent ») :
  * les 5 portes R1-R5 refusent chacune pour SON motif, et le motif est nommé ;
  * les moyennes pondérées sont exactes (le PnL reste vrai après renfort) ;
  * le funding déjà accru n'est JAMAIS rétro-projeté sur le nouveau notional ;
  * un renfort n'arrive JAMAIS sur une position qui devait fermer (ordre du lifecycle) ;
  * bout en bout : `GestionnaireCarry.tick` grossit la position SANS écrire de CLOSE.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_renfort import (DELAI_MIN_RENFORT_MS, ECART_MIN_FRACTION, MOTIF,
                                               est_amortie, peut_renforcer, renforcer)

H = 3_600_000
T0 = 1_760_000_000_000


def _pos(**kw):
    p = {"coin": "HYPE", "mode": "LIVE", "notional_usdt": 500.0, "marge_usdt": 50.0,
         "levier": 10.0, "entry_ts_ms": T0, "last_accrual_ts_ms": T0,
         "entry_perp_px": 100.0, "base_bps_entree": 20.0, "base_mid_bps_entree": 20.0,
         "cout_entree_bps": 12.0, "funding_accrued_usdt": 1.0}
    p.update(kw)
    return p


# ------------------------------------------------------------------ R2 : l'amortissement mesuré

def test_est_amortie_compare_des_dollars_pas_une_extrapolation():
    # 500 $ × 12 bps = 0,60 $ de coût d'entrée payé
    assert est_amortie(_pos(funding_accrued_usdt=0.60)) is True
    assert est_amortie(_pos(funding_accrued_usdt=0.59)) is False


def test_est_amortie_position_sans_cout_entree_est_amortie_par_construction():
    assert est_amortie(_pos(cout_entree_bps=0.0, funding_accrued_usdt=0.0)) is True


# ------------------------------------------------------------------ R1-R5 : chaque porte, son motif

@pytest.mark.parametrize("kwargs, motif_attendu", [
    (dict(viable=False, amortissable=True), "COIN_NON_VIABLE_CE_TICK"),
    (dict(viable=True, amortissable=False), "AJOUT_NON_AMORTISSABLE_AVANT_FIN_DE_VIE"),
])
def test_portes_dures_refusent_avec_leur_motif(kwargs, motif_attendu):
    ok, motif = peut_renforcer(_pos(), marge_cible_usd=100.0, now_ms=T0 + 50 * H, **kwargs)
    assert (ok, motif) == (False, motif_attendu)


def test_marge_cible_egale_ou_inferieure_ne_bouge_pas():
    for cible in (50.0, 40.0, 0.0):
        ok, motif = peut_renforcer(_pos(), marge_cible_usd=cible, now_ms=T0 + 50 * H,
                                   viable=True, amortissable=True)
        assert (ok, motif) == (False, "MARGE_DEJA_AU_NIVEAU")


def test_R4_ecart_trop_faible_refuse_juste_sous_le_seuil_et_passe_juste_au_dessus():
    juste_sous = 50.0 * (1.0 + ECART_MIN_FRACTION) - 0.01
    ok, motif = peut_renforcer(_pos(), marge_cible_usd=juste_sous, now_ms=T0 + 50 * H,
                               viable=True, amortissable=True)
    assert (ok, motif) == (False, "ECART_TROP_FAIBLE")
    ok, _ = peut_renforcer(_pos(), marge_cible_usd=50.0 * (1.0 + ECART_MIN_FRACTION) + 0.01,
                           now_ms=T0 + 50 * H, viable=True, amortissable=True)
    assert ok is True


def test_R5_un_renfort_par_24h():
    p = _pos(dernier_renfort_ts_ms=T0)
    ok, motif = peut_renforcer(p, marge_cible_usd=100.0, now_ms=T0 + DELAI_MIN_RENFORT_MS - 1,
                               viable=True, amortissable=True)
    assert (ok, motif) == (False, "RENFORT_DEJA_FAIT_AUJOURD_HUI")
    ok, _ = peut_renforcer(p, marge_cible_usd=100.0, now_ms=T0 + DELAI_MIN_RENFORT_MS,
                           viable=True, amortissable=True)
    assert ok is True


# ------------------------------------------------------------------ R3 : les moyennes pondérées

def test_renfort_moyennes_ponderees_exactes():
    p = renforcer(_pos(), marge_cible_usd=100.0, now_ms=T0 + 50 * H,
                  prix_perp=110.0, base_bps=10.0, cout_entree_bps_ajout=8.0)
    # marge 50 -> 100 avec levier 10 : notional 500 -> 1000, donc poids 50/50
    assert p["marge_usdt"] == 100.0
    assert p["notional_usdt"] == 1000.0
    assert p["entry_perp_px"] == pytest.approx(105.0)       # (100 + 110) / 2
    assert p["base_bps_entree"] == pytest.approx(15.0)      # (20 + 10) / 2
    assert p["cout_entree_bps"] == pytest.approx(10.0)      # (12 + 8) / 2
    assert p["renforts"] == 1
    assert p["dernier_renfort_ts_ms"] == T0 + 50 * H


def test_renfort_poids_asymetriques():
    # marge 50 -> 150 : ajout = 2× l'existant -> poids 1/3 ancien, 2/3 nouveau
    p = renforcer(_pos(), marge_cible_usd=150.0, now_ms=T0, prix_perp=130.0)
    assert p["notional_usdt"] == 1500.0
    assert p["entry_perp_px"] == pytest.approx(100.0 / 3 + 2 * 130.0 / 3)


def test_mesure_absente_garde_l_ancienne_valeur_jamais_inventee():
    p = renforcer(_pos(), marge_cible_usd=100.0, now_ms=T0, prix_perp=None,
                  base_bps=None, cout_entree_bps_ajout=None)
    assert p["entry_perp_px"] == 100.0
    assert p["base_bps_entree"] == 20.0
    assert p["cout_entree_bps"] == 12.0


def test_funding_deja_accru_reste_intact_jamais_retro_projete():
    p = renforcer(_pos(funding_accrued_usdt=3.25), marge_cible_usd=200.0, now_ms=T0)
    assert p["funding_accrued_usdt"] == 3.25          # gagné sur l'ANCIEN notional


def test_position_incoherente_est_rendue_telle_quelle():
    for casse in ({"levier": 0.0}, {"marge_usdt": 0.0}, {"notional_usdt": 0.0}):
        avant = _pos(**casse)
        assert renforcer(avant, marge_cible_usd=100.0, now_ms=T0) == avant


def test_renfort_ne_mute_jamais_la_position_source():
    avant = _pos()
    copie = dict(avant)
    renforcer(avant, marge_cible_usd=100.0, now_ms=T0, prix_perp=110.0)
    assert avant == copie


# ------------------------------------------------------------------ invariants économiques

@pytest.mark.parametrize("cible", [70.1, 100.0, 250.0, 1000.0])
def test_invariant_le_renfort_ne_reduit_jamais_rien(cible):
    avant = _pos()
    apres = renforcer(avant, marge_cible_usd=cible, now_ms=T0, prix_perp=90.0, base_bps=1.0)
    assert apres["notional_usdt"] > avant["notional_usdt"]
    assert apres["marge_usdt"] > avant["marge_usdt"]
    assert apres["levier"] == avant["levier"]            # le risque par dollar NE MONTE PAS
    assert apres["entry_ts_ms"] == avant["entry_ts_ms"]  # l'âge (donc l'amortissement) est conservé
    assert apres["funding_accrued_usdt"] == avant["funding_accrued_usdt"]


def test_invariant_le_levier_est_conserve_donc_la_marge_finance_bien_le_notional():
    p = renforcer(_pos(), marge_cible_usd=137.0, now_ms=T0)
    assert p["notional_usdt"] == pytest.approx(p["marge_usdt"] * p["levier"])


# ------------------------------------------------------------------ bout en bout, dans le lifecycle

#: levier VOLONTAIREMENT bas et pire-hausse VOLONTAIREMENT petite : ces tests parlent du
#: renfort, pas du verrou de liquidation (qui a ses propres tests). Un fixture qui se fait
#: liquider testerait la sortie, pas ce qu'on veut prouver ici.
_LEVIER = 3.0
_INPUTS = {"levier_utilise": _LEVIER, "levier_max": _LEVIER, "perp_px": 100.0,
           "pire_hausse_observee": 0.01, "liquidite_spot_usd": 500_000.0}


def _decision(viable=True, **kw):
    # 🔴 21/07 — funding d'ENTREE 0.125 -> 0.45 : la porte du cout d'opportunite refuse
    # d'ouvrir au plancher. Ces tests portent sur le RENFORT (grossir sans payer de sortie),
    # pas sur la rentabilite du plancher. Les tests de la MATH d'amortissement, plus bas,
    # gardent 0.125 : ils calculent, ils n'ouvrent pas.
    d = {"coin": "HYPE", "viable": viable, "funding_bps_h": 0.45, "cout_entree_bps": 12.0,
         "base_bps": 20.0, "gain_net_24h_bps": 3.0, "liquidite_spot_usd": 50_000.0}
    d.update(kw)
    return d


def test_bout_en_bout_le_tick_renforce_sans_jamais_fermer():
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    g = GestionnaireCarry(mode="TEST_FIXTURE")
    inputs = dict(_INPUTS)
    ctx = {"capital_usd": 5000.0}
    evt = g.tick(_decision(), inputs, now_ms=T0, marge_usd=50.0, risque_contexte=ctx)
    assert evt["ouvert"] is True
    pos = g.ouvertes["HYPE"]
    assert pos["notional_usdt"] == 50.0 * _LEVIER

    # on force l'amortissement MESURÉ (le funding réel au plancher mettrait ~100 h)
    pos["funding_accrued_usdt"] = 5.0
    evt = g.tick(_decision(), inputs, now_ms=T0 + 2 * H, marge_usd=100.0, risque_contexte=ctx)

    assert evt["ferme"] is None                          # aucune fermeture : donc aucun frais de sortie
    assert evt["renfort"]["notional_ajoute"] == pytest.approx(50.0 * _LEVIER, abs=1.0)
    assert g.ouvertes["HYPE"]["notional_usdt"] == pytest.approx(100.0 * _LEVIER, abs=1.0)
    assert [e.get("reason") for e in g.journal.rows() if e.get("kind") == "RENFORT"] == [MOTIF]
    assert not [e for e in g.journal.rows() if e.get("kind") == "CLOSE"]


def test_bout_en_bout_pas_de_renfort_quand_la_decision_n_est_plus_viable():
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    g = GestionnaireCarry(mode="TEST_FIXTURE")
    inputs = dict(_INPUTS)
    g.tick(_decision(), inputs, now_ms=T0, marge_usd=50.0, risque_contexte={"capital_usd": 5000.0})
    g.ouvertes["HYPE"]["funding_accrued_usdt"] = 5.0
    evt = g.tick(_decision(viable=False), inputs, now_ms=T0 + 2 * H, marge_usd=100.0,
                 risque_contexte={"capital_usd": 5000.0})
    assert "renfort" not in evt
    assert evt.get("renfort_refuse") == "COIN_NON_VIABLE_CE_TICK"
    assert g.ouvertes["HYPE"]["notional_usdt"] == 50.0 * _LEVIER


# ------------------------------------------------------------------ R2 : le VRAI test économique

def test_ajout_amortissable_le_dollar_ajoute_doit_avoir_le_temps():
    from hl_observer.funding.carry_renfort import ajout_amortissable
    # 12 bps à 0,125 bps/h = 96 h pour rembourser l'entrée du montant ajouté
    assert ajout_amortissable(cout_entree_bps_ajout=12.0, funding_bps_h=0.125,
                              heures_restantes=96.0) is True
    assert ajout_amortissable(cout_entree_bps_ajout=12.0, funding_bps_h=0.125,
                              heures_restantes=95.9) is False


@pytest.mark.parametrize("funding", [0.0, -0.5])
def test_ajout_jamais_amortissable_sans_revenu(funding):
    from hl_observer.funding.carry_renfort import ajout_amortissable
    assert ajout_amortissable(cout_entree_bps_ajout=12.0, funding_bps_h=funding,
                              heures_restantes=10_000.0) is False


def test_bout_en_bout_position_en_fin_de_vie_n_est_pas_renforcee():
    """Une position à 2 h de son âge max n'a plus le temps d'amortir un ajout : R2 refuse."""
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    g = GestionnaireCarry(mode="TEST_FIXTURE")
    ctx = {"capital_usd": 5000.0}
    g.tick(_decision(), dict(_INPUTS), now_ms=T0, marge_usd=50.0, risque_contexte=ctx)
    evt = g.tick(_decision(), dict(_INPUTS), now_ms=T0 + 2 * H, marge_usd=100.0,
                 risque_contexte=ctx, age_max_h=4.0)
    assert evt.get("renfort_refuse") == "AJOUT_NON_AMORTISSABLE_AVANT_FIN_DE_VIE"
    assert g.ouvertes["HYPE"]["notional_usdt"] == 50.0 * _LEVIER


def test_bout_en_bout_R6_la_porte_de_risque_garde_aussi_le_renfort():
    """Ajouter du notional EST une ouverture : le capital disponible doit la couvrir."""
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    g = GestionnaireCarry(mode="TEST_FIXTURE")
    g.tick(_decision(), dict(_INPUTS), now_ms=T0, marge_usd=50.0,
           risque_contexte={"capital_usd": 5000.0})
    # capital ridicule : la marge ajoutée ne passe pas la porte
    evt = g.tick(_decision(), dict(_INPUTS), now_ms=T0 + 2 * H, marge_usd=100.0,
                 risque_contexte={"capital_usd": 60.0})
    assert str(evt.get("renfort_refuse", "")).startswith("PORTE_RISQUE:")
    assert g.ouvertes["HYPE"]["notional_usdt"] == 50.0 * _LEVIER


# ------------------------------------------------------------------ le chemin de PRODUCTION

def test_chemin_production_le_renfort_est_ecrit_au_ledger_et_visible(tmp_path):
    """`tick_multi_sur_disque` est le seul chemin qui tourne vraiment. On y prouve :
       * le renfort survit à la persistance (positions rechargées depuis le disque) ;
       * il est écrit au ledger sous son propre `kind` ;
       * il n'entre PAS dans le PnL réalisé (il ne réalise rien) ;
       * le capital déployé (`notional_ouvert_usdt`) monte — c'est tout l'intérêt.
    """
    from hl_observer.funding.carry_positions_store import (charger_gestionnaire, etat_carry,
                                                           tick_multi_sur_disque)

    mesures = {"HYPE": {"decision": _decision(), "inputs": dict(_INPUTS), "funding": 0.125}}
    tick_multi_sur_disque(tmp_path, mesures, now_ms=T0, mode="TEST_FIXTURE",
                          capital_usd=500.0)
    etat0 = etat_carry(tmp_path, mode="TEST_FIXTURE")
    assert etat0["positions_ouvertes"] == 1
    notional0 = etat0["notional_ouvert_usdt"]
    assert notional0 > 0

    # capital ×4 -> marge cible ×4 : l'écart dépasse largement les 40 % de R4
    tick_multi_sur_disque(tmp_path, mesures, now_ms=T0 + 2 * H, mode="TEST_FIXTURE",
                          capital_usd=2000.0)
    etat1 = etat_carry(tmp_path, mode="TEST_FIXTURE")

    assert etat1["renforts"] == 1
    assert etat1["positions_renforcees"] == 1
    assert etat1["notional_ouvert_usdt"] > notional0        # le capital travaille davantage
    assert etat1["closes"] == 0                             # AUCUN aller-retour : zéro frais de sortie
    assert etat1["realized_net_pnl_usdc"] == 0.0            # un renfort ne réalise rien
    assert charger_gestionnaire(tmp_path, mode="TEST_FIXTURE").ouvertes["HYPE"]["renforts"] == 1


def test_chemin_production_deux_renforts_le_meme_jour_sont_impossibles(tmp_path):
    from hl_observer.funding.carry_positions_store import etat_carry, tick_multi_sur_disque

    mesures = {"HYPE": {"decision": _decision(), "inputs": dict(_INPUTS), "funding": 0.125}}
    tick_multi_sur_disque(tmp_path, mesures, now_ms=T0, mode="TEST_FIXTURE", capital_usd=500.0)
    for i in (2, 4, 6):                                     # trois passes dans la même journée
        tick_multi_sur_disque(tmp_path, mesures, now_ms=T0 + i * H, mode="TEST_FIXTURE",
                              capital_usd=2000.0 * i)
    assert etat_carry(tmp_path, mode="TEST_FIXTURE")["renforts"] == 1     # R5 tient
