"""CHAQUE FAMILLE DU COFFRE A UN RÔLE MESURÉ OU UNE EXCLUSION MOTIVÉE — plus de troisième état.

POURQUOI (17/11/2026). Six familles restaient ``A_CABLER`` : déclarées, en attente d'une
hypothèse, jamais mesurées. L'objectif exige mieux : un rôle consommé ET mesuré, ou une exclusion
motivée. La question qu'un état d'attente laisse ouverte est la seule qui compte — cette famille
PEUT-elle changer quelque chose ?

Ces tests verrouillent les cinq mesures, et surtout ce qu'elles refusent :

* une minute sans trade n'est pas une capacité nulle observée ;
* un flux de capital dont le montant est inconnu reste un flux — il fausse le PnL quand même ;
* une ligne ``overshoot`` porte des prix du FUTUR : elle est un résultat, jamais une entrée ;
* un horodatage 0 est une valeur, pas une absence (défaut d'idiome attrapé à l'écriture).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_roles_familles as R  # noqa: E402

MINUTE = 60_000
JOUR = 86_400_000


def _trade(coin, ts, prix, taille):
    return {"coin": coin, "exchange_ts_ms": ts, "price": prix, "size": taille}


# ─────────────────────────── trades_marche : la capacité ───────────────────────────
def test_la_capacite_est_le_notionnel_MEDIAN_d_une_minute_rapporte_a_l_ordre():
    r = R.capacite_par_coin([
        _trade("BTC", 0, 100.0, 700.0),                 # minute 0 : 70 000 USD
        _trade("BTC", MINUTE, 100.0, 350.0),            # minute 1 : 35 000 USD
        _trade("BTC", 2 * MINUTE, 100.0, 1_050.0),      # minute 2 : 105 000 USD
    ], ordre_usd=350.0)
    btc = r["par_coin"]["BTC"]
    assert btc["notionnel_median_par_minute_usd"] == 70_000.0
    assert btc["multiple_de_l_ordre"] == 200.0
    assert r["role"] == R.ROLE_CAPACITE
    assert r["coins_a_capacite_large"] == 1


def test_un_horodatage_ZERO_est_une_valeur_pas_une_absence():
    """Défaut d'idiome attrapé à l'écriture : `a or b` jetait un horodatage 0, pourtant valide."""
    r = R.capacite_par_coin([_trade("BTC", 0, 100.0, 10.0)])
    assert r["lignes_ignorees"] == 0
    assert r["coins"] == 1


def test_un_coin_ETROIT_est_nomme_au_lieu_d_etre_moyenne_avec_les_autres():
    r = R.capacite_par_coin([_trade("GROS", 0, 100.0, 10_000.0), _trade("PETIT", 0, 1.0, 35.0)],
                            ordre_usd=350.0)
    etroits = dict(r["coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre"])
    assert etroits == {"PETIT": 0.1}
    assert r["part_coins_a_capacite_large"] == 0.5


def test_une_ligne_de_trade_INCOMPLETE_est_comptee_jamais_devinee():
    r = R.capacite_par_coin([_trade("BTC", 0, None, 1.0), _trade("BTC", 0, 100.0, 0.0),
                             {"coin": "BTC", "price": 1.0, "size": 1.0}, _trade("BTC", 5, 2.0, 3.0)])
    assert r["lignes_lues"] == 4
    assert r["lignes_ignorees"] == 3
    assert r["par_coin"]["BTC"]["notionnel_median_par_minute_usd"] == 6.0


def test_une_minute_SANS_trade_n_est_pas_un_volume_nul_observe():
    """Deux minutes actives sur une fenêtre de onze : la médiane porte sur les minutes ACTIVES."""
    r = R.capacite_par_coin([_trade("BTC", 0, 100.0, 10.0), _trade("BTC", 10 * MINUTE, 100.0, 10.0)])
    btc = r["par_coin"]["BTC"]
    assert btc["minutes_avec_trades"] == 2
    assert r["minutes_dans_la_fenetre"] == 11
    assert btc["part_minutes_avec_trades"] == round(2 / 11, 4)
    assert btc["notionnel_median_par_minute_usd"] == 1_000.0, "jamais dilue par des minutes vides"


# ─────────────────────────── liquidation : le risque ───────────────────────────
def test_le_risque_compte_evenements_comptes_coins_et_JOURS_actifs():
    lignes = [
        {"vault": "0xA", "coin": "POPCAT", "ts_ms": 0, "dir": "Auto-Deleveraging", "px": 0.15, "sz": 1000.0},
        {"vault": "0xa", "coin": "POPCAT", "ts_ms": 5, "dir": "Auto-Deleveraging", "px": 0.15, "sz": 1000.0},
        {"vault": "0xb", "coin": "BTC", "ts_ms": 3 * JOUR, "dir": "Liquidated Cross Long", "px": 100.0, "sz": 1.0},
        {"coin": "BTC", "ts_ms": 1},                                  # sans compte : ignoree
    ]
    r = R.risque_de_liquidation(lignes)
    assert r["evenements"] == 3 and r["lignes_ignorees"] == 1
    assert r["comptes_touches"] == 2, "la casse d'une adresse ne cree pas un second compte"
    assert r["jours_avec_evenement"] == 2
    assert r["evenements_par_jour_actif"] == 1.5
    assert r["par_type"]["Auto-Deleveraging"] == 2
    assert r["notionnel_total_usd"] == 400.0


# ─────────────────────────── vault_ledger : les flux ───────────────────────────
def test_un_flux_au_MONTANT_INCONNU_reste_un_flux():
    """Il fausse le PnL du jour quand même : on le compte, et on dit que le montant manque."""
    lignes = [
        {"vault": "0xa", "ts_ms": 0, "type": "vaultDeposit", "delta_usd": 60.0, "montant_connu": True},
        {"vault": "0xa", "ts_ms": 10, "type": "vaultWithdraw", "delta_usd": None,
         "est_retrait": True, "montant_connu": False},
        {"vault": "0xb", "ts_ms": JOUR, "type": "vaultWithdraw", "delta_usd": -25.0},
    ]
    r = R.flux_de_capital(lignes)
    assert r["depots"] == 1 and r["retraits"] == 2
    assert r["montants_inconnus"] == 1
    assert r["jours_compte_avec_flux"] == 2, "deux flux le meme jour sur le meme compte = un jour"
    assert r["comptes_avec_flux"] == 2
    assert r["total_retraits_usd"] == 25.0, "un montant inconnu n'est jamais remplace par une valeur"
    assert r["part_retraits"] == round(2 / 3, 4)


# ─────────────────────── overshoot : résultat, jamais entrée ───────────────────────
def test_l_overshoot_est_EXCLU_comme_entree_parce_qu_il_porte_le_FUTUR():
    lignes = [
        {"coin": "RNDR", "overshoot_bps": -191.75, "sens": "SELL_OVERSHOOT",
         "mid_fwd_15s": 6.89, "mid_fwd_120s": 6.89, "reversion_bps": 0.0},
        {"coin": "BTC", "overshoot_bps": 40.0, "sens": "BUY_OVERSHOOT", "reversion_bps": -12.0,
         "mid_fwd_60s": 1.0},
        {"coin": "ETH"},                                                # sans amplitude : ignoree
    ]
    r = R.resultat_overshoot(lignes)
    assert r["role"] == R.ROLE_RESULTAT
    assert r["evenements"] == 2 and r["lignes_ignorees"] == 1
    assert r["part_avec_champs_du_futur"] == 1.0, "toutes les lignes portent des prix posterieurs"
    assert "LOOK_AHEAD" in r["motif_d_exclusion_comme_entree"]
    assert r["amplitude_abs_bps"]["p99"] == 191.75
    assert r["part_reversion_nulle"] == 0.5


# ─────────────────── micro_l2 / micro_trades : l'applicabilité ───────────────────
def test_l_applicabilite_est_la_part_des_ouvertures_sur_les_coins_COUVERTS():
    r = R.applicabilite_microstructure({"BTC": 60, "ETH": 30, "kPEPE": 10}, ["BTC", "ETH", "SOL"])
    assert r["part_des_ouvertures_couvertes"] == 0.9
    assert r["ouvertures_sur_coins_micro"] == 90
    assert r["principaux_coins_NON_couverts"] == [("kPEPE", 10)]
    assert r["role"] == R.ROLE_APPLICABILITE


def test_sans_aucune_ouverture_la_part_est_INCONNUE_et_non_zero():
    r = R.applicabilite_microstructure({}, ["BTC"])
    assert r["part_des_ouvertures_couvertes"] is None


def test_un_chemin_de_prix_FIGE_est_compte_a_part_de_la_reversion_nulle():
    """67,3 % des lignes du coffre : quatre prix futurs identiques au prix de l'evenement, sur des
    perps delistes. Une reversion nulle OBSERVEE sur un marche vivant n'est pas la meme chose."""
    fige = {"coin": "RNDR", "overshoot_bps": -191.75, "mid_at_event": 6.8952,
            "mid_fwd_15s": 6.8952, "mid_fwd_30s": 6.8952, "mid_fwd_60s": 6.8952,
            "mid_fwd_120s": 6.8952, "reversion_bps": 0.0}
    vivant = {"coin": "ETH", "overshoot_bps": -40.0, "mid_at_event": 100.0,
              "mid_fwd_15s": 100.1, "mid_fwd_30s": 100.0, "mid_fwd_60s": 100.2,
              "mid_fwd_120s": 100.0, "reversion_bps": 0.0}
    r = R.resultat_overshoot([fige, vivant])
    assert r["part_reversion_nulle"] == 1.0, "les deux reversions valent zero..."
    assert r["chemins_figes"] == 1 and r["part_chemins_figes"] == 0.5, (
        "... mais un seul des deux marches etait fige")


# ─────────── 17/11 : LA CAPACITÉ CONFRONTÉE AU VOLUME RÉELLEMENT TRAITÉ ───────────
#
# Mesuré sur 15–17/11 : pour le coin médian, une minute de marché n'échange que 1,51 fois l'ordre
# paper de 350 USD, et 5 % seulement des coins ont une capacité large. Le simulateur de
# réplication compte frais taker et demi-écart, pas l'impact : son net est donc optimiste sur la
# part du volume traitée dans des coins étroits. Cette part doit être publiée avec le net.
def _capacite(**multiples):
    return {"par_coin": {c: {"multiple_de_l_ordre": m} for c, m in multiples.items()}}


def test_le_volume_est_reparti_en_TROIS_classes_jamais_deux():
    r = R.exposition_a_la_capacite(
        {"BTC": 700.0, "PETIT": 200.0, "JAMAIS_VU": 100.0},
        _capacite(BTC=5_000.0, PETIT=0.4))
    assert r["volume_total_usd"] == 1_000.0
    assert r["part_volume_coins_etroits"] == 0.2
    assert r["part_volume_capacite_inconnue"] == 0.1
    assert r["part_volume_capacite_mesuree_suffisante"] == 0.7
    assert r["principaux_coins_etroits"] == [("PETIT", 200.0)]
    assert r["principaux_coins_inconnus"] == [("JAMAIS_VU", 100.0)]


def test_une_capacite_NON_MESUREE_n_est_jamais_comptee_comme_suffisante():
    """Aucun trade de marché observé pour un coin ≠ marché profond."""
    r = R.exposition_a_la_capacite({"FANTOME": 500.0}, _capacite())
    assert r["part_volume_capacite_inconnue"] == 1.0
    assert r["part_volume_capacite_mesuree_suffisante"] == 0.0
    # un coin present dans la table mais sans multiple calcule est inconnu lui aussi
    r = R.exposition_a_la_capacite({"X": 10.0}, {"par_coin": {"X": {"multiple_de_l_ordre": None}}})
    assert r["part_volume_capacite_inconnue"] == 1.0


def test_sans_aucun_volume_les_parts_sont_INCONNUES_et_non_nulles():
    r = R.exposition_a_la_capacite({}, _capacite(BTC=10.0))
    assert r["volume_total_usd"] == 0.0
    assert r["part_volume_coins_etroits"] is None


def test_le_simulateur_publie_son_volume_PAR_COIN_sans_changer_le_resultat():
    """La ventilation est additive : la somme par coin doit égaler le volume total du simulateur."""
    import numpy as np

    from hl_observer.backtesting import copy_vault_copiability as cop
    from hl_observer.backtesting import copy_vault_replication_paper as rep

    heure = 3_600_000
    t0 = 1_790_000_000_000 // heure * heure
    instantanes = ((t0 + i * 60_000, {"BTC": 100.0 + i * 0.01, "ETH": 50.0}) for i in range(600))
    panel = cop.build_mid_panel(instantanes, stale_ms=120_000)
    portefeuille = [(t0 + i * 60_000, 1_000.0, {"BTC": 2.0, "ETH": 4.0}) for i in range(0, 600, 10)]
    config = rep.ReplicationConfig()
    resultat = rep.run_replication(portefeuille, panel, {"BTC": 1.0, "ETH": 1.0}, config)
    par_coin = resultat["volume_usd_par_coin"]
    assert set(par_coin) <= {"BTC", "ETH"} and par_coin, "au moins un ordre doit avoir ete traite"
    duree_jours = max(1e-9, (resultat["steps"] - 1) * config.rebalance_ms / 86_400_000)
    volume_total = resultat["turnover_per_day"] * config.capital_usd * duree_jours
    assert sum(par_coin.values()) == __import__("pytest").approx(volume_total, rel=1e-3)
    assert np.isfinite(resultat["final_equity_usd"])
