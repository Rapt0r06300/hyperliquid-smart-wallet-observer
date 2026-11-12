"""La recherche du labo ne se lance pas quand aucun trade n'est exécutable sur la période d'entraînement.

Cas réel du 2026-11-12 : 128 essais (32 minutes) tous « non mesurables » — les carnets collectés
localement ne portaient pas l'identité de leur connexion, que le moteur exige pour exécuter un trade.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting import copy_vault_local_lab as local_lab  # noqa: E402
from hl_observer.backtesting import copy_vault_train_executability as sonde  # noqa: E402

T0 = 1_800_000_600_000                     # dix minutes après l'heure pile (aucun funding traversé)


def _carnet(instant, *, connexion="cx", epoque=0, ligne=1):
    row = {"coin": "ETH", "ts_ms": instant, "bid": 2000.0, "ask": 2001.0, "capacity_usd": 8_000.0,
           "bids5": [[2000.0, 5.0]], "asks5": [[2001.0, 4.0]], "source_line": ligne, "causal_observation": True}
    if connexion is not None:
        row["connection_id"] = connexion
        row["l2_gap_epoch"] = epoque
    return row


def _donnees(*, connexion="cx", avec_sortie=True):
    entree = {"event_id": "e1", "ts_ms": T0 + 1_000, "coin": "ETH", "direction": 1, "action": "ADD",
              "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS",
              "is_snapshot": False, "observed_at_ms": T0 + 1_025, "received_at_ms": T0 + 1_025}
    metaordres = cv.cluster_metaorders([entree])[0]
    carnets = [_carnet(T0, connexion=connexion, ligne=1), _carnet(T0 + 62_000, connexion=connexion, ligne=2)]
    if avec_sortie:
        carnets.append(_carnet(T0 + 363_000, connexion=connexion, ligne=3))      # sortie à +300 s
    bornes = {"train_start_ms": T0 - 60_000, "train_end_ms": T0 + 600_000}
    return metaordres, {"ETH": carnets}, bornes


def test_un_segment_executable_laisse_passer_la_recherche():
    metaordres, carnets, bornes = _donnees()
    resultat = sonde.sonder_train(metaordres, carnets, bornes)
    assert resultat["executable"] is True and resultat["raison"] is None
    assert resultat["trades_executables_par_horizon_ms"]["300000"] == 1 and resultat["meilleur_horizon_ms"] == 300_000
    assert resultat["signaux_train"] == 1


def test_des_carnets_sans_identite_de_connexion_arretent_la_recherche_et_disent_pourquoi():
    metaordres, carnets, bornes = _donnees(connexion=None)
    resultat = sonde.sonder_train(metaordres, carnets, bornes)
    assert resultat["executable"] is False and resultat["raison"] == sonde.RAISON
    assert set(resultat["trades_executables_par_horizon_ms"].values()) == {0}
    # à 300 s le carnet de sortie existe et c'est l'identité qui manque ; aux autres horizons, la sortie
    assert resultat["refus_par_motif"]["L2_CONNECTION_IDENTITY_INCOMPLETE"] == 1
    assert set(resultat["refus_par_motif"]) <= {"L2_CONNECTION_IDENTITY_INCOMPLETE", "STALE_OR_MISSING_EXIT_BOOK",
                                                 "FUNDING_BOUNDARY_UNPRICED"}
    phrase = sonde.resume_lisible(resultat)
    assert "aucun trade exécutable sur 1 signaux" in phrase and "identité de connexion" in phrase


def test_une_collecte_qui_s_arrete_avant_la_sortie_est_nommee():
    metaordres, carnets, bornes = _donnees(avec_sortie=False)
    resultat = sonde.sonder_train(metaordres, carnets, bornes)
    assert resultat["executable"] is False
    assert "STALE_OR_MISSING_EXIT_BOOK" in resultat["refus_par_motif"]
    assert "la collecte s'arrête avant la fin de la position" in sonde.resume_lisible(resultat)


def test_un_signal_hors_du_segment_train_ne_compte_pas():
    metaordres, carnets, _bornes = _donnees()
    resultat = sonde.sonder_train(metaordres, carnets, {"train_start_ms": T0 + 3_600_000, "train_end_ms": T0 + 7_200_000})
    assert resultat["executable"] is False and resultat["signaux_train"] == 0 and resultat["refus_par_motif"] == {}


def test_le_labo_appelle_la_sonde_avant_de_lancer_des_essais():
    source = Path(local_lab.__file__).read_text(encoding="utf-8")
    avant_la_recherche = source.split("campaign_config, campaign_config_sha = _campaign_search_config(bounds)")[0]
    assert "sonde = sonder_train(metaorders, books, bounds)" in avant_la_recherche
    assert '"reason": sonde["raison"], "train_executability": sonde' in avant_la_recherche
    assert local_lab.sonder_train is sonde.sonder_train


def _donnees_deux_coins():
    """ETH exécutable (3 carnets), SOL non exécutable (pas de carnet de sortie)."""
    entrees = []
    for coin in ("ETH", "SOL"):
        entrees.append({"event_id": "e-" + coin, "ts_ms": T0 + 1_000, "coin": coin, "direction": 1,
                        "action": "ADD", "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0,
                        "move_frac": 0.01, "source": "LIVE_WS", "is_snapshot": False,
                        "observed_at_ms": T0 + 1_025, "received_at_ms": T0 + 1_025})
    metaordres = cv.cluster_metaorders(entrees)[0]
    carnets = {
        "ETH": [_carnet(T0, ligne=1), _carnet(T0 + 62_000, ligne=2), _carnet(T0 + 363_000, ligne=3)],
        "SOL": [_carnet(T0, ligne=1), _carnet(T0 + 62_000, ligne=2)],   # pas de sortie à +300 s
    }
    for coin, rows in carnets.items():
        for r in rows:
            r["coin"] = coin
    bornes = {"train_start_ms": T0 - 60_000, "train_end_ms": T0 + 600_000}
    return metaordres, carnets, bornes


def test_la_ventilation_par_coin_est_la_carte_de_collecte():
    metaordres, carnets, bornes = _donnees_deux_coins()
    resultat = sonde.sonder_train(metaordres, carnets, bornes)
    assert resultat["executable"] is True                                   # ETH exécutable → la recherche peut tourner
    assert resultat["par_coin"]["ETH"]["executables"] == 1
    assert resultat["par_coin"]["SOL"]["executables"] == 0
    assert resultat["par_coin"]["SOL"]["non_executables"] == 1
    assert "STALE_OR_MISSING_EXIT_BOOK" in resultat["par_coin"]["SOL"]["refus_par_motif"]
    # SOL est en tête de la file de collecte, ETH n'y est pas
    cible = resultat["coins_a_collecter"]
    assert cible and cible[0]["coin"] == "SOL" and cible[0]["non_executables"] == 1
    assert all(c["coin"] != "ETH" for c in cible)
    assert sonde.coins_a_collecter(resultat) == cible                       # helper réutilisable


def test_le_resume_nomme_les_coins_a_collecter():
    metaordres, carnets, bornes = _donnees(connexion=None)                  # rien d'exécutable
    resultat = sonde.sonder_train(metaordres, carnets, bornes)
    phrase = sonde.resume_lisible(resultat)
    assert "collecter en priorité" in phrase and "ETH" in phrase
