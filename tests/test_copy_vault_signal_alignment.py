"""Signaux évaluables : la découpe temporelle du labo ne porte que sur ce qui peut être mesuré."""
from __future__ import annotations

from hl_observer.backtesting import copy_vault_local_lab as lab
from hl_observer.backtesting.copy_vault_signal_alignment import evaluable_signals

DAY = 86_400_000


def _mo(coin: str, ts: int, action: str = "OPEN") -> dict:
    return {"coin": coin, "signal_ts_ms": ts, "action": action}


def test_un_signal_sans_carnet_causal_recent_n_est_pas_evaluable():
    books = {"BTC": [{"ts_ms": 1_000}, {"ts_ms": 50_000}]}
    metaorders = [
        _mo("BTC", 900),                 # avant tout carnet
        _mo("BTC", 1_000, "ADD"),        # carnet reçu au même instant : causal
        _mo("BTC", 31_001),              # dernier carnet vieux de 30,001 s : trop ancien
        _mo("BTC", 49_999),              # le carnet de 50 000 est POSTÉRIEUR : jamais utilisé
        _mo("BTC", 60_000, "ADD"),
        _mo("ETH", 60_000),              # aucun carnet pour ce coin
    ]

    resultat = evaluable_signals(metaorders, books, min_signals_per_day=1)

    assert resultat["timestamps"] == [1_000, 60_000]
    assert resultat["aligned_adds"] == 2
    assert resultat["summary"]["evaluable_by_action"] == {"ADD": 2}
    assert resultat["summary"]["signals"] == 6
    # règle par défaut : un jour avec 2 signaux évaluables est trop clairsemé pour porter la découpe
    defaut = evaluable_signals(metaorders, books)
    assert defaut["timestamps"] == [] and defaut["aligned_adds"] == 2
    assert defaut["summary"]["evaluable_utc_days"] == 0
    assert defaut["summary"]["sparse_utc_days_excluded_from_split"] == 1


def test_carnets_non_tries_et_gros_volumes_restent_exacts():
    books = {"BTC": [{"ts_ms": t} for t in (5_000, 1_000, 3_000)]}
    metaorders = [_mo("BTC", t) for t in range(0, 40_000, 7)]
    resultat = evaluable_signals(metaorders, books, min_signals_per_day=1)
    attendu = [t for t in range(0, 40_000, 7) if 1_000 <= t <= 35_000]
    assert resultat["timestamps"] == attendu


def test_la_decoupe_ignore_les_jours_sans_carnet():
    """Régression du 2026-11-10 : 768 jours de signaux sans carnet plaçaient TRAIN dans le vide."""
    historiques = [_mo("BTC", jour * DAY + 1_000) for jour in range(1, 701)]
    recents = [_mo("BTC", (800 + jour) * DAY + 1_000 + k * 60_000)
               for jour in range(10) for k in range(12)]
    # quelques signaux isolés AVEC carnet, étalés sur d'anciens jours : ils ne doivent pas porter la découpe
    isoles = [_mo("BTC", (700 + jour) * DAY + 1_000) for jour in range(0, 60, 4)]
    books = {"BTC": [{"ts_ms": (800 + jour) * DAY + 500 + k * 60_000}
                     for jour in range(10) for k in range(12)]
                    + [{"ts_ms": (700 + jour) * DAY + 500} for jour in range(0, 60, 4)]}

    alignement = evaluable_signals(historiques + isoles + recents, books)
    bornes = lab._bounds(alignement["timestamps"])
    tous = lab._bounds([row["signal_ts_ms"] for row in historiques + isoles + recents])

    assert alignement["summary"]["evaluable_utc_days"] == 10
    assert alignement["summary"]["sparse_utc_days_excluded_from_split"] == 15
    assert bornes is not None and tous is not None
    # la découpe sur tous les signaux ferme TRAIN bien avant le premier carnet : aucun trade possible
    assert tous["train_end_ms"] < 800 * DAY
    # la découpe sur les signaux évaluables place TRAIN là où des carnets existent
    assert bornes["train_start_ms"] >= 800 * DAY
    evaluables_train = [t for t in alignement["timestamps"]
                        if bornes["train_start_ms"] <= t <= bornes["train_end_ms"]]
    assert len(evaluables_train) >= 5


def test_l_evaluabilite_ne_depend_pas_des_donnees_futures():
    """Ajouter des carnets ou des signaux POSTÉRIEURS ne change pas le statut des signaux passés."""
    books = {"BTC": [{"ts_ms": 1_000}]}
    passe = [_mo("BTC", 1_500), _mo("BTC", 40_000)]
    avant = evaluable_signals(passe, books, min_signals_per_day=1)
    apres = evaluable_signals(
        passe + [_mo("BTC", 90_000)], {"BTC": [{"ts_ms": 1_000}, {"ts_ms": 89_000}]}, min_signals_per_day=1)
    assert avant["timestamps"] == [1_500]
    assert apres["timestamps"][:1] == [1_500] and 40_000 not in apres["timestamps"]
