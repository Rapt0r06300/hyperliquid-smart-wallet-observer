from hl_observer.config.settings import Settings
from hl_observer.markets.universe import build_market_universe, is_exotic_market


def test_is_exotic_market_flags_hip3_rwa_builder_spot():
    # Exotiques (HIP-3 actions/matieres, builder, spot) -> exclus
    for coin in ["XYZ:TSLA", "CASH:WTI", "XYZ:SILVER", "@107", "@1", "#2160"]:
        assert is_exotic_market(coin) is True, coin
    # Perps crypto standards -> gardes
    for coin in ["BTC", "ETH", "SOL", "HYPE", "ZEC", "kPEPE", "WIF"]:
        assert is_exotic_market(coin) is False, coin


def test_build_universe_excludes_exotic_by_default():
    settings = Settings()
    meta = {
        "universe": [
            {"name": "BTC"},
            {"name": "ETH"},
            {"name": "HYPE"},
            {"name": "XYZ:TSLA"},
            {"name": "CASH:WTI"},
            {"name": "@107"},
        ]
    }
    universe = build_market_universe(settings, meta_payload=meta)
    coins = set(universe.coins)
    assert {"BTC", "ETH", "HYPE"} <= coins
    assert not any(is_exotic_market(c) for c in coins)
    assert "XYZ:TSLA" not in coins and "CASH:WTI" not in coins and "@107" not in coins


def test_build_universe_can_opt_in_to_exotic():
    settings = Settings()
    settings.market_universe.include_builder_and_rwa_perps = True
    meta = {"universe": [{"name": "BTC"}, {"name": "XYZ:TSLA"}]}
    coins = set(build_market_universe(settings, meta_payload=meta).coins)
    assert "XYZ:TSLA" in coins
