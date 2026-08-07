"""[AUD-268..291] Registre agrege des venues : 11 adaptateurs offline, frontieres live honnetes."""
from hl_observer.venues import registre_venues as registre


def test_onze_venues_offline_ready():
    r = registre.registre()
    assert len(r) == 11
    assert set(registre.offline_ready()) == {"bybit", "okx", "coinbase", "deribit", "kraken",
                                             "drift", "gmx", "nansen", "dune", "glassnode", "defillama"}


def test_frontieres_live_honnetes():
    f = registre.par_frontiere_live()
    # payants (cle requise)
    assert set(f["REQUIRES_KEY"]) == {"nansen", "dune", "glassnode"}
    # publics gratuits / reseau seulement
    assert set(f["REQUIRES_NETWORK"]) == {"bybit", "okx", "coinbase", "deribit", "kraken",
                                          "drift", "gmx", "defillama"}


def test_ready_multi_venue():
    rmv = registre.ready_multi_venue()
    assert rmv["ready"] is True and rmv["manquants"] == [] and rmv["n_venues"] == 11
