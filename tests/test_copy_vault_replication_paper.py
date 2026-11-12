"""Réplication PAPER sous contraintes réelles (350 USD, ordre minimal 10 USD, frais, écart, funding)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hl_observer.backtesting import copy_vault_replication_paper as R
from hl_observer.backtesting.copy_vault_copiability_entrees import PricePanel
from hl_observer.fees.hyperliquid_fees import MIN_ORDER_VALUE_USD, TAKER_PERP_BPS

HEURE = 3_600_000
JOUR = 24 * HEURE
T0 = 1_780_000_000_000 // JOUR * JOUR


def _panel(prix_par_coin: dict[str, list[float]], *, pas_ms: int = 60_000, stale_ms: int = 120_000) -> PricePanel:
    longueur = len(next(iter(prix_par_coin.values())))
    ts = T0 + np.arange(longueur, dtype=np.int64) * pas_ms
    return PricePanel(ts=ts, px=np.column_stack([np.array(v, dtype=float) for v in prix_par_coin.values()]),
                      coins=tuple(prix_par_coin), provenance="test", stale_ms=stale_ms)


def _minutes(heures: int) -> int:
    return heures * 60 + 1


def _portefeuille(tailles: dict[str, float], nav: float, heures: int, *, pas_ms: int = 300_000):
    return [(T0 + k * pas_ms, nav, dict(tailles)) for k in range(heures * HEURE // pas_ms + 1)]


CONFIG = R.ReplicationConfig()
ECARTS = {"BTC": 1.0, "ETH": 2.0}


def test_prix_immobiles_la_valeur_ne_baisse_que_des_couts_payes():
    """Invariant comptable : sans mouvement de prix, variation du compte = -(frais + écart), au centime."""
    panel = _panel({"BTC": [100.0] * _minutes(60)})
    resultat = R.run_replication(_portefeuille({"BTC": 10.0}, 1_000.0, 60), panel, ECARTS, CONFIG)
    assert resultat["status"] == "OK" and resultat["orders"] == 1                 # une entrée, puis plus rien à faire
    cout = 350.0 * (TAKER_PERP_BPS + 1.0) / 1e4
    assert resultat["fees_usd"] == pytest.approx(350.0 * TAKER_PERP_BPS / 1e4)
    assert resultat["net_total_usd"] == pytest.approx(-cout, abs=1e-9)
    assert resultat["mean_gross_exposure"] == pytest.approx(1.0, abs=0.02)          # jamais de levier
    # la première journée commence après le délai de réaction : elle est incomplète, donc non comptée
    assert resultat["complete_days"] == 1 and resultat["daily_net_usd"][-1] == pytest.approx(0.0, abs=1e-9)


def test_le_gain_suit_le_leader_moins_les_couts_et_les_frictions_ne_rapportent_jamais():
    hausse = [100.0 * (1.0 + 0.0001 * i) for i in range(_minutes(50))]             # +0,6 % par heure
    panel = _panel({"BTC": hausse})
    portefeuille = _portefeuille({"BTC": 5.0}, 1_000.0, 50)                        # leader exposé à 50 % de son compte
    decomposition = R.decomposer_les_pertes(portefeuille, panel, ECARTS, CONFIG)
    nets = decomposition["net_usd_per_day"]
    assert nets["sans_friction"] > 0
    ordre = ["sans_friction", "avec_delai", "avec_frais_et_ecart", "avec_funding", "complet_ordre_minimal_et_bande"]
    assert all(nets[a] >= nets[b] - 1e-9 for a, b in zip(ordre, ordre[1:], strict=False))        # chaque friction coûte ou ne change rien
    assert decomposition["cost_usd_per_day"]["avec_frais_et_ecart"] > 0
    assert decomposition["full"]["mean_gross_exposure"] < 0.6                       # même levier que le leader, pas plus
    # doubler les frais ne peut jamais augmenter le résultat
    cher = R.run_replication(portefeuille, panel, ECARTS, replace(CONFIG, taker_fee_bps=2 * TAKER_PERP_BPS))
    assert cher["net_total_usd"] < decomposition["full"]["net_total_usd"]


def test_un_portefeuille_trop_morcele_ne_peut_pas_etre_copie_avec_350_usd():
    """50 lignes de 2 % = 7 USD chacune : sous l'ordre minimal de la plateforme. Aucune position, aucun gain inventé."""
    coins = {f"C{i}": [10.0 * (1.0 + 0.0002 * k) for k in range(_minutes(30))] for i in range(50)}
    panel = _panel(coins)
    portefeuille = _portefeuille({c: 2.0 for c in coins}, 1_000.0, 30)             # 50 x 20 USD sur 1 000
    resultat = R.run_replication(portefeuille, panel, {c: 1.0 for c in coins}, CONFIG)
    assert MIN_ORDER_VALUE_USD == 10.0 and resultat["orders"] == 0
    assert resultat["orders_refused_by_venue_minimum"] > 0 and resultat["net_total_usd"] == 0.0
    # le même portefeuille sans la contrainte de la plateforme aurait été copié : l'écart est mesuré, pas caché
    sans = R.run_replication(portefeuille, panel, {c: 1.0 for c in coins}, replace(CONFIG, min_order_usd=0.0, band_fraction=0.0))
    assert sans["orders"] >= 50 and sans["net_total_usd"] > 0 and sans["mean_gross_exposure"] > 0.9


def test_ecart_inconnu_ou_prix_absent_pas_d_ordre():
    panel = _panel({"BTC": [100.0] * _minutes(30), "ETH": [50.0] * _minutes(30)})
    portefeuille = _portefeuille({"BTC": 5.0, "ETH": 10.0, "SOL": 3.0}, 1_000.0, 30)
    resultat = R.run_replication(portefeuille, panel, {"BTC": 1.0}, CONFIG)       # ETH sans écart mesuré, SOL sans prix
    assert resultat["untradable_coins"] == {"ETH": "ECART_INCONNU", "SOL": "PRIX_INCONNU"}
    assert resultat["orders"] == 1 and resultat["spread_cost_usd"] == pytest.approx(175.0 * 1.0 / 1e4)


def test_portefeuille_perime_cible_inconnue_on_ne_touche_a_rien():
    panel = _panel({"BTC": [100.0] * _minutes(40)})
    court = _portefeuille({"BTC": 10.0}, 1_000.0, 2)                                # le leader n'est plus observé après 2 h
    resultat = R.run_replication(court, panel, ECARTS, CONFIG)
    assert resultat["orders"] == 1 and resultat["steps"] <= 3                      # la simulation s'arrête avec la preuve
    # réapparaît à plat 28 h plus tard, puis reste observé : la fermeture suit le délai de réaction
    trou = court + [(T0 + 30 * HEURE - 300_000 + k * 300_000, 1_000.0, {}) for k in range(30)]
    resultat = R.run_replication(trou, panel, ECARTS, CONFIG)
    assert resultat["steps_target_unknown"] >= 25 and resultat["orders"] == 2      # entrée, attente, puis fermeture
    assert resultat["mean_gross_exposure"] > 0.8                                   # la position est TENUE pendant le trou
    # une journée passée à tenir un portefeuille périmé ne mesure pas la stratégie : elle n'est pas comptée
    long_trou = court + [(T0 + 60 * HEURE + k * 300_000, 1_000.0, {}) for k in range(30)]
    panel_long = _panel({"BTC": [100.0] * _minutes(64)})
    aveugle = R.run_replication(long_trou, panel_long, ECARTS, CONFIG)
    assert aveugle["complete_days"] == 0 and aveugle["days_excluded_leader_unobserved"] >= 1
    assert R.run_replication(long_trou, panel_long, ECARTS,
                             replace(CONFIG, min_target_known_fraction=0.0))["complete_days"] >= 1


def test_la_cible_n_utilise_jamais_un_portefeuille_posterieur():
    """Métamorphique : changer le portefeuille du leader après la fin de la fenêtre de prix ne change rien."""
    panel = _panel({"BTC": [100.0 + 0.01 * i for i in range(_minutes(26))]})
    passe = _portefeuille({"BTC": 5.0}, 1_000.0, 26)
    futur = passe + [(T0 + 26 * HEURE + 1, 1_000.0, {"BTC": -50.0})]               # retournement APRÈS la fenêtre
    assert R.run_replication(passe, panel, ECARTS, CONFIG) == R.run_replication(futur, panel, ECARTS, CONFIG)
    # délai de réaction : le leader sort 5 min avant l'heure ; un copieur qui réagit en 10 min ne voit
    # encore que l'ancien portefeuille à l'heure pile et ne sort qu'une heure plus tard
    change = [(T0 + k * 300_000, 1_000.0, {"BTC": 5.0}) for k in range(35)]         # long jusqu'à 2 h 50
    change += [(T0 + k * 300_000, 1_000.0, {}) for k in range(35, 150)]              # à plat à partir de 2 h 55
    communs = {"debut_grille_ms": T0 + HEURE}
    lent = R.run_replication(change, panel, ECARTS, replace(CONFIG, reaction_ms=600_000), **communs)
    vif = R.run_replication(change, panel, ECARTS, replace(CONFIG, reaction_ms=0), **communs)
    assert lent["steps"] == vif["steps"] and lent["mean_gross_exposure"] > vif["mean_gross_exposure"]


def test_funding_paye_quand_il_est_connu_jamais_suppose_nul_sinon():
    panel = _panel({"BTC": [100.0] * _minutes(30)})
    portefeuille = _portefeuille({"BTC": 10.0}, 1_000.0, 30)
    taux = {"BTC": np.full(len(panel.ts), 0.0001)}                                 # 1 bp par heure, payé par le long
    connu = R.run_replication(portefeuille, panel, ECARTS, CONFIG, funding_rates=taux)
    assert connu["funding_coverage"] == pytest.approx(1.0) and connu["funding_usd"] > 0
    assert connu["funding_usd"] == pytest.approx(350.0 * 0.0001 * (connu["steps"] - 1), rel=0.02)
    inconnu = R.run_replication(portefeuille, panel, ECARTS, CONFIG)
    assert inconnu["funding_usd"] == 0.0 and inconnu["funding_coverage"] == 0.0    # inconnu, signalé, pas compté comme nul
    assert connu["net_total_usd"] < inconnu["net_total_usd"]


def test_prix_perime_la_journee_n_est_pas_comptee_et_rien_n_est_traite():
    prix = [100.0] * _minutes(74)
    panel = _panel({"BTC": prix})
    ts = panel.ts[(panel.ts < T0 + 30 * HEURE) | (panel.ts > T0 + 33 * HEURE)]      # trou de prix de 3 h le 2e jour
    troue = PricePanel(ts=ts, px=np.full((len(ts), 1), 100.0), coins=("BTC",), provenance="test", stale_ms=120_000)
    portefeuille = _portefeuille({"BTC": 10.0}, 1_000.0, 74)
    resultat = R.run_replication(portefeuille, troue, ECARTS, CONFIG)
    assert resultat["steps_valuation_unknown"] >= 2
    # 2e journée : valorisation inconnue pendant le trou, donc écartée ; seule la 3e (complète) est comptée
    assert resultat["complete_days"] == 1
    assert R.run_replication(portefeuille, panel, ECARTS, CONFIG)["complete_days"] == 2


def test_entrees_vides_non_mesurable_et_deterministe():
    panel = _panel({"BTC": [100.0] * _minutes(30)})
    assert R.run_replication([], panel, ECARTS)["status"] == "UNMEASURABLE"
    portefeuille = _portefeuille({"BTC": 10.0}, 1_000.0, 30)
    assert R.run_replication(portefeuille, panel, ECARTS) == R.run_replication(portefeuille, panel, ECARTS)
    assert R.ReplicationConfig().capital_usd == 350.0 and R.ReplicationConfig().taker_fee_bps == TAKER_PERP_BPS


# ------------------------------------------------------------------ portefeuille entier : un état par dex

def _snap(compte, t, positions, nav, dex=None):
    ligne = {"vault": compte, "ts_ms": int(t), "nav_usd": nav,
             "positions": [{"coin": c, "szi": s} for c, s in positions.items()]}
    if dex:
        ligne["dex"] = dex
    return ligne


def test_le_portefeuille_entier_reunit_le_dex_principal_et_les_dex_hip3():
    minute = 60_000
    snaps = [
        _snap("0xA", T0, {"BTC": 1.0}, 1_000.0),                              # avant tout suivi du dex xyz
        _snap("0xA", T0 + 5 * minute, {"BTC": 1.0}, 1_000.0),
        _snap("0xA", T0 + 6 * minute, {"xyz:XYZ100": -3.0}, 400.0, dex="xyz"),
        _snap("0xA", T0 + 10 * minute, {"BTC": 2.0}, 1_100.0),
        _snap("0xA", T0 + 11 * minute, {"xyz:XYZ100": -3.0}, 410.0, dex="xyz"),
        _snap("0xA", T0 + 40 * minute, {"BTC": 2.0}, 1_100.0),                # le dex xyz est muet depuis 29 min
        _snap("0xB", T0, {"ETH": 5.0}, 500.0),                                # compte suivi sur le seul dex principal
        _snap("0xC", T0, {"xyz:NVDA": 1.0}, 50.0, dex="xyz"),                 # dex principal jamais observé
        {"vault": "0xA", "ts_ms": T0 + 12 * minute, "positions": [{"coin": "BTC", "szi": "abc"}]},
    ]
    portefeuilles, rejets = R.portefeuilles_depuis_instantanes(snaps)
    assert set(portefeuilles) == {"0xa", "0xb"}
    a = {t - T0: (nav, tailles) for t, nav, tailles in portefeuilles["0xa"]}
    assert a[0] == (1_000.0, {"BTC": 1.0}) and a[5 * minute] == (1_000.0, {"BTC": 1.0})        # ancien régime
    assert a[6 * minute] == (1_400.0, {"BTC": 1.0, "xyz:XYZ100": -3.0})                       # réunion, valeurs sommées
    assert a[10 * minute] == (1_500.0, {"BTC": 2.0, "xyz:XYZ100": -3.0})
    assert a[11 * minute] == (1_510.0, {"BTC": 2.0, "xyz:XYZ100": -3.0})
    assert 40 * minute not in a                                  # incomplet : jamais complété par un état périmé
    assert rejets == {"position_illisible": 1, "portefeuille_incomplet_dex_muet": 1, "compte_sans_dex_principal": 1}
    assert portefeuilles["0xb"] == [(T0, 500.0, {"ETH": 5.0})]
    # l'ordre d'arrivée des instantanés ne change rien
    assert R.portefeuilles_depuis_instantanes(list(reversed(snaps)))[0] == portefeuilles


def test_un_dex_qui_entre_dans_le_suivi_ne_fabrique_aucune_ouverture():
    """Les positions HIP-3 révélées au premier relevé du dex existaient déjà : aucun événement n'en sort."""
    from hl_observer.backtesting import copy_vault_copiability as cop

    minute = 60_000
    snaps = [
        _snap("0xA", T0, {"BTC": 1.0}, 1_000.0),
        _snap("0xA", T0 + 5 * minute, {"BTC": 2.0}, 1_000.0),                     # vraie décision : +1 BTC
        _snap("0xA", T0 + 6 * minute, {"xyz:XYZ100": -3.0}, 400.0, dex="xyz"),    # le dex xyz entre dans le suivi
        _snap("0xA", T0 + 10 * minute, {"BTC": 2.0}, 1_000.0),
        _snap("0xA", T0 + 11 * minute, {"xyz:XYZ100": -5.0}, 400.0, dex="xyz"),   # vraie décision : -2 XYZ100
    ]
    complets, _ = R.instantanes_complets(snaps)
    assert [(x["ts_ms"] - T0) // minute for x in complets] == [0, 5, 6, 10, 11]
    assert [x["perimetre_change"] for x in complets] == [False, False, True, False, False]
    evenements, _vus, rejets = cop.position_events_from_snapshots(complets)
    decisions = [(row.coin, int((row.time - T0) // minute), row.start_pos, row.after) for row in evenements.itertuples()]
    assert decisions == [("BTC", 0, 0.0, 1.0), ("BTC", 5, 1.0, 2.0), ("xyz:XYZ100", 11, -3.0, -5.0)]
    assert rejets["perimetre_change_sans_evenement"] == 1
    # sans la marque (ancien comportement), la position révélée aurait été prise pour une ouverture
    naifs = [{**x, "perimetre_change": False} for x in complets]
    assert len(cop.position_events_from_snapshots(naifs)[0]) == 4
    # un compte suivi sur le seul dex principal n'a aucun changement de périmètre
    seuls, _ = R.instantanes_complets([_snap("0xB", T0, {"ETH": 1.0}, 10.0), _snap("0xB", T0 + minute, {}, 10.0)])
    assert [x["perimetre_change"] for x in seuls] == [False, False]
