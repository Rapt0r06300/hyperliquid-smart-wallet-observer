"""B11 — filtre directionnel post-purge : n'autoriser que la direction relâchée par la purge."""
from __future__ import annotations

from hl_observer.backtesting.liquidation_cascade import Cluster
from hl_observer.backtesting.post_liquidation_direction import (
    NOTIONNEL_PURGE_MIN_USD, direction_relachee, autorise,
)


def _cluster(long: bool, notl: float, coin="HYPE"):
    return Cluster(coin=coin, prix_centre=10.0, n_comptes=5, notionnel_total_usd=notl, long=long)


def test_pas_de_purge_pas_de_filtre():
    assert direction_relachee([]) is None
    assert autorise("LONG", []) is True and autorise("SHORT", []) is True


def test_longs_liquides_relache_le_haut_long():
    clusters = [_cluster(long=True, notl=200_000.0)]     # vente forcée (longs liquidés)
    assert direction_relachee(clusters) == "LONG"
    assert autorise("LONG", clusters) is True
    assert autorise("SHORT", clusters) is False          # ne pas vendre dans l'offre déjà purgée


def test_shorts_liquides_relache_le_bas_short():
    clusters = [_cluster(long=False, notl=200_000.0)]    # achat forcé (shorts liquidés)
    assert direction_relachee(clusters) == "SHORT"
    assert autorise("SHORT", clusters) is True
    assert autorise("LONG", clusters) is False


def test_sous_le_seuil_pas_une_purge():
    petit = [_cluster(long=True, notl=NOTIONNEL_PURGE_MIN_USD - 1.0)]
    assert direction_relachee(petit) is None
    assert autorise("SHORT", petit) is True              # pas de purge -> pas de filtre


def test_accepte_aussi_les_dicts():
    d = [Cluster(coin="X", prix_centre=1.0, n_comptes=4, notionnel_total_usd=100_000.0, long=True).as_dict()]
    assert direction_relachee(d) == "LONG"


def test_egalite_pas_de_direction_nette():
    clusters = [_cluster(long=True, notl=100_000.0), _cluster(long=False, notl=100_000.0)]
    assert direction_relachee(clusters) is None
