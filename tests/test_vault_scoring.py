"""Score multi-facteurs des vaults (rectif Flo 23/07) : on ne sélectionne PLUS sur l'APR. On prouve
les 8 facteurs mesurés, le composite, et le filtre de rétention (jeune/drawdown/peu copyable = rejeté)."""
from __future__ import annotations

from hl_observer.experimental import vault_scoring as VS


def _snaps(navs, positions, dds=None, flux=None):
    out = []
    for i, nav in enumerate(navs):
        s = {"ts_ms": 1000 * i, "nav_usd": nav, "positions": positions}
        if dds:
            s["drawdown_pct"] = dds[i]
        if flux:
            s["depot_retrait_net_usd"] = flux[i]
        out.append(s)
    return out


def test_rendement_net_corrige_des_flux():
    # nav 100k -> 110k mais +5k déposé -> vrai gain = 5k / 100k = 5 %
    snaps = _snaps([100_000, 110_000], [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}], flux=[0, 5_000])
    assert round(VS.rendement_net(snaps), 4) == 0.05


def test_facteurs_regularite_drawdown_concentration():
    snaps = _snaps([100, 101, 102], [{"coin": "BTC", "szi": 1.0, "entryPx": 100.0}])
    assert VS.regularite(snaps) == 1.0                                 # jamais en baisse
    baisse = _snaps([100, 90, 95], [{"coin": "BTC", "szi": 1.0, "entryPx": 100.0}])
    assert VS.regularite(baisse) < 1.0 and VS.drawdown_max_pct(baisse) >= 10.0
    # concentration : 2 coins d'expo égale -> HHI 0.5
    snap = {"positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 100.0}, {"coin": "ETH", "szi": 100.0, "entryPx": 1.0}]}
    assert round(VS.concentration_hhi(snap), 3) == 0.5


def test_copyabilite_part_expo_executable():
    snap = {"positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 100.0},     # 100 $ exécutable
                          {"coin": "OBSCURE", "szi": 100.0, "entryPx": 1.0}]}  # 100 $ non exécutable
    assert VS.copyabilite(snap, {"BTC"}) == 0.5
    assert VS.copyabilite(snap, set()) == 0.0                          # rien d'exécutable connu -> 0


def test_scorer_et_retenir():
    snaps = _snaps([100_000, 101_000, 102_000],
                   [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}, {"coin": "ETH", "szi": 10.0, "entryPx": 2_000}])
    sc = VS.scorer_vault(snaps, age_j=300.0, tvl_usd=2_000_000, coins_executables={"BTC", "ETH"})
    assert 0.0 <= sc["composite"] <= 1.0 and set(sc["normalises"]) == set(VS.POIDS)
    ok, raison = VS.retenu(sc)
    assert ok and raison == ""
    # un vault trop jeune est rejeté quel que soit son composite
    jeune = VS.scorer_vault(snaps, age_j=10.0, tvl_usd=2_000_000, coins_executables={"BTC", "ETH"})
    assert VS.retenu(jeune) == (False, "TROP_JEUNE")


def test_scoring_point_in_time_ignore_le_futur():
    """Rectif Flo : à une date, le score n'utilise QUE les snapshots ≤ cette date (anti-fuite)."""
    snaps = _snaps([100_000, 101_000, 500_000],                       # 3e snapshot = envolée FUTURE
                   [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}])
    # sans cutoff : le rendement inclut l'envolée future
    sans = VS.scorer_vault(snaps, age_j=300, tvl_usd=2_000_000, coins_executables={"BTC"})
    # avec cutoff à la 2e date (ts_ms=1000) : n'utilise que les 2 premiers snapshots
    avec = VS.scorer_vault(snaps, age_j=300, tvl_usd=2_000_000, coins_executables={"BTC"}, date_max_ms=1000)
    assert avec["n_snapshots"] == 2 and sans["n_snapshots"] == 3
    assert avec["facteurs"]["pnl_net"] < sans["facteurs"]["pnl_net"]   # le futur (envolée) est exclu


def test_classer_ordonne_par_composite():
    snaps_bon = _snaps([100_000, 103_000], [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}])
    snaps_plat = _snaps([100_000, 100_000], [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}])
    cl = VS.classer({"0xBON": snaps_bon, "0xPLAT": snaps_plat},
                    meta={"0xBON": {"age_j": 300, "tvl_usd": 3_000_000}, "0xPLAT": {"age_j": 300, "tvl_usd": 3_000_000}},
                    coins_executables={"BTC"})
    assert [c["vault"] for c in cl][0] == "0xBON"                      # le meilleur rendement en tête
    assert cl[0]["composite"] >= cl[1]["composite"]
