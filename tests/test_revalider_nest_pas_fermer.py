"""REVALIDER N'EST PAS FERMER (21/07) — le plus gros poste de destruction après le churn.

LA MESURE
---------
L'aller-retour vaut **22 bps**. La porte d'âge max fermait une position VIVANTE tous les
14 jours « pour revalider ». Au funding plancher (3,000 bps/jour de revenu brut) :

    tenir 14 j  -> le renouvellement coûte 1,571 bps/j =  **52,4 % du revenu détruit**
    tenir 90 j  ->                          0,244 bps/j =    8,1 %
    tenir 365 j ->                          0,060 bps/j =    2,0 %

**Notre propre règle d'hygiène brûlait la moitié du revenu.**

Or la revalidation a DÉJÀ lieu : chaque tick recalcule la décision et dispose de ses propres
sorties (funding non rentable, liquidation, base convergée, donnée absente prolongée, hors
shortlist). L'âge max était un **doublon** de ces sorties — un doublon qui coûtait 52 %.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_position_lifecycle import (SORTIE_AGE, GestionnaireCarry,
                                                          raison_de_sortie)

H = 3_600_000
T0 = 1_760_000_000_000
INPUTS = {"levier_utilise": 3.0, "levier_max": 3.0, "perp_px": 100.0,
          "pire_hausse_observee": 0.01, "liquidite_spot_usd": 500_000.0}


def _dec(viable=True):
    # 🔴 21/07 — funding d'OUVERTURE 0.125 -> 0.45 (porte du cout d'opportunite). Ces tests
    # portent sur « revalider n'est pas fermer », pas sur le plancher. Les positions
    # construites DIRECTEMENT plus bas (funding_bps_h_entree) gardent 0.125 : elles existent
    # deja, elles ne passent pas par la porte d'ouverture.
    return {"coin": "HYPE", "viable": viable, "funding_bps_h": 0.45, "cout_entree_bps": 12.0,
            "base_bps": 20.0, "gain_net_24h_bps": 3.0, "liquidite_spot_usd": 50_000.0}


def _ouvrir(now=T0):
    g = GestionnaireCarry(mode="TEST_FIXTURE")
    g.tick(_dec(), dict(INPUTS), now_ms=now, marge_usd=50.0,
           risque_contexte={"capital_usd": 5000.0})
    g.ouvertes["HYPE"]["funding_accrued_usdt"] = 50.0      # amortie : l'anti-churn laisse passer
    return g


# ------------------------------------------------------------------ le cœur

def test_une_position_VIABLE_a_l_age_max_n_est_PAS_fermee():
    """LE correctif. 22 bps épargnés à chaque anniversaire."""
    g = _ouvrir()
    evt = g.tick(_dec(), dict(INPUTS), now_ms=T0 + 400 * H, marge_usd=50.0, age_max_h=336.0,
                 risque_contexte={"capital_usd": 5000.0})
    assert evt["ferme"] is None
    assert evt["revalidee_sans_fermer"]["revalidations"] == 1
    assert evt["revalidee_sans_fermer"]["frais_evites_bps"] == 22.0
    assert "HYPE" in g.ouvertes


def test_une_position_NON_viable_a_l_age_max_est_bien_fermee():
    """Le garde-fou reste : on ne garde pas un zombie. C'est la VIABILITÉ qui tranche,
    plus l'anniversaire."""
    g = _ouvrir()
    evt = g.tick(_dec(viable=False), dict(INPUTS), now_ms=T0 + 400 * H, marge_usd=50.0,
                 age_max_h=336.0, risque_contexte={"capital_usd": 5000.0})
    assert evt["ferme"] == SORTIE_AGE
    assert "HYPE" not in g.ouvertes


def test_l_horloge_repart_apres_une_revalidation():
    """Sans remise à zéro, la porte se redéclencherait à CHAQUE tick une fois l'âge dépassé —
    et le drapeau ne servirait à rien."""
    g = _ouvrir()
    g.tick(_dec(), dict(INPUTS), now_ms=T0 + 400 * H, marge_usd=50.0, age_max_h=336.0,
           risque_contexte={"capital_usd": 5000.0})
    # c'est l'HORLOGE D'AGE qui repart — jamais `entry_ts_ms` (voir le test de régression)
    assert g.ouvertes["HYPE"]["age_reference_ts_ms"] == T0 + 400 * H
    assert g.ouvertes["HYPE"]["entry_ts_ms"] == T0
    evt2 = g.tick(_dec(), dict(INPUTS), now_ms=T0 + 401 * H, marge_usd=50.0, age_max_h=336.0,
                  risque_contexte={"capital_usd": 5000.0})
    assert "revalidee_sans_fermer" not in evt2, "l'horloge n'a pas redémarré"


def test_les_revalidations_sont_COMPTEES():
    """Une position renouvelée dix fois doit le DIRE — sinon son âge réel disparaît du
    rapport, et on ne saurait plus depuis quand on la tient."""
    g = _ouvrir()
    for i in (400, 800, 1200):
        g.tick(_dec(), dict(INPUTS), now_ms=T0 + i * H, marge_usd=50.0, age_max_h=336.0,
               risque_contexte={"capital_usd": 5000.0})
    assert g.ouvertes["HYPE"]["revalidations"] == 3


# ------------------------------------------------------------------ la fonction pure

def test_raison_de_sortie_rend_l_AGE_sans_drapeau_de_revalidation():
    """Contrat explicite : sans le drapeau, le comportement historique est préservé."""
    pos = {"coin": "X", "entry_ts_ms": T0, "cout_entree_bps": 11.0, "base_bps_entree": 0.0,
           "funding_bps_h_entree": 0.125, "notional_usdt": 500.0, "levier": 2.0,
           "marge_ratio": 0.5, "levier_max": 10.0, "pire_hausse_entree": 0.01,
           "funding_accrued_usdt": 1.0, "liquidite_spot_usd": 400_000.0}
    assert raison_de_sortie(pos, now_ms=T0 + 400 * H, funding_bps_h_courant=0.125,
                            age_max_h=336.0) == SORTIE_AGE
    pos["revalidee_viable"] = True
    assert raison_de_sortie(pos, now_ms=T0 + 400 * H, funding_bps_h_courant=0.125,
                            age_max_h=336.0) is None


def test_les_AUTRES_sorties_ne_sont_PAS_neutralisees_par_le_drapeau():
    """🔴 Le risque du correctif : qu'un drapeau « viable » rende une position immortelle.
    Le drapeau ne couvre QUE l'âge — liquidation et funding gardent toute leur autorité."""
    pos = {"coin": "X", "entry_ts_ms": T0, "cout_entree_bps": 11.0, "base_bps_entree": 0.0,
           "funding_bps_h_entree": 0.125, "notional_usdt": 500.0, "levier": 2.0,
           "marge_ratio": 0.5, "levier_max": 10.0, "pire_hausse_entree": 0.01,
           "funding_accrued_usdt": 1.0, "liquidite_spot_usd": 400_000.0, "revalidee_viable": True}
    # une hausse énorme doit toujours déclencher la sortie liquidation
    motif = raison_de_sortie(pos, now_ms=T0 + 400 * H, funding_bps_h_courant=0.125,
                             hausse_depuis_entree=0.90, age_max_h=336.0)
    assert motif is not None and motif != SORTIE_AGE


# ------------------------------------------------------------------ l'arithmétique du gain

@pytest.mark.parametrize("jours, part_max_pct", [(14, 55), (90, 10), (365, 3)])
def test_le_cout_du_renouvellement_decroit_avec_la_duree(jours, part_max_pct):
    """Le nombre qui a motivé le correctif, gravé pour qu'il ne se reperde pas."""
    aller_retour_bps = 22.0
    revenu_jour_bps = 0.125 * 24
    part = 100.0 * (aller_retour_bps / jours) / revenu_jour_bps
    assert part <= part_max_pct, "%d j -> %.1f %% du revenu" % (jours, part)


# ------------------------------------------------------------------ 🔴 le bug que j'ai failli livrer

def test_la_revalidation_ne_TOUCHE_JAMAIS_entry_ts_ms():
    """🔴 RÉGRESSION ATTRAPÉE AVANT LIVRAISON. Ma première version remettait `entry_ts_ms`
    à zéro pour l'horloge d'âge. Or `funding_settlement` compte les règlements horaires
    DEPUIS l'entrée : le funding réglé chutait de TOUT l'accru (mesuré : 5,00 $ → 0,00 $),
    puis remontait une heure plus tard. Exactement le yoyo tué le 20/07.

    `entry_ts_ms` est la vérité de QUAND on est entré. Il ne doit jamais mentir."""
    from hl_observer.paper_trading.funding_settlement import decouper

    g = _ouvrir()
    g.ouvertes["HYPE"]["funding_accrued_usdt"] = 5.0
    avant = decouper(g.ouvertes["HYPE"], now_ms=T0 + 400 * H)["net_funding_settled"]

    g.tick(_dec(), dict(INPUTS), now_ms=T0 + 400 * H, marge_usd=50.0, age_max_h=336.0,
           risque_contexte={"capital_usd": 5000.0})
    apres = decouper(g.ouvertes["HYPE"], now_ms=T0 + 400 * H)["net_funding_settled"]

    assert g.ouvertes["HYPE"]["entry_ts_ms"] == T0, "entry_ts_ms a été réécrit"
    assert g.ouvertes["HYPE"]["age_reference_ts_ms"] == T0 + 400 * H
    assert apres >= avant, "le funding RÉGLÉ a chuté : discontinuité de PnL stable"


def test_l_age_utilise_l_horloge_DEDIEE_pas_l_entree():
    """Les deux horloges doivent être distinctes : l'âge se remet à zéro, l'entrée jamais."""
    from hl_observer.funding.carry_position_lifecycle import raison_de_sortie

    pos = {"coin": "X", "entry_ts_ms": T0, "age_reference_ts_ms": T0 + 390 * H,
           "cout_entree_bps": 11.0, "base_bps_entree": 0.0, "funding_bps_h_entree": 0.125,
           "notional_usdt": 500.0, "levier": 2.0, "marge_ratio": 0.5, "levier_max": 10.0,
           "pire_hausse_entree": 0.01, "funding_accrued_usdt": 1.0,
           "liquidite_spot_usd": 400_000.0}
    # 400 h depuis l'ENTRÉE mais seulement 10 h depuis la dernière revalidation
    assert raison_de_sortie(pos, now_ms=T0 + 400 * H, funding_bps_h_courant=0.125,
                            age_max_h=336.0) is None
