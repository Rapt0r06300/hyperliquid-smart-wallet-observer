"""Backfill fills + reconstruction d'épisodes (rectif Flo 23/07) : on prouve OPEN/ADD/REDUCE/CLOSE
reconstruits depuis les fills, et surtout la DISTINCTION décision alpha vs RETRAIT (reduce pro-rata
multi-coins simultané). Pagination + dédup + couverture. Aucun réseau (fills injectés)."""
from __future__ import annotations

from hl_observer.collection import vault_fills_backfill as VB


def test_plan_de_requetes_fenetre():
    plan = VB.plan_de_requetes(0, 3 * VB.MS_PAR_HEURE, fenetre_ms=VB.MS_PAR_HEURE)
    assert plan == [(0, VB.MS_PAR_HEURE), (VB.MS_PAR_HEURE, 2 * VB.MS_PAR_HEURE), (2 * VB.MS_PAR_HEURE, 3 * VB.MS_PAR_HEURE)]
    assert VB.plan_de_requetes(10, 10) == []


def test_parser_et_dedup():
    brut = [{"time": 1000, "coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long",
             "startPosition": "0", "oid": 1},
            {"time": 1000, "coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long",
             "startPosition": "0", "oid": 1}]                          # doublon (bord de pagination)
    fills = VB.dedupliquer(VB.parser_fills(brut, vault="0xA"))
    assert len(fills) == 1 and fills[0]["signe"] == 1 and fills[0]["coin"] == "SOL"


def test_reconstruire_open_add_reduce_close():
    fills = VB.parser_fills([
        {"time": 1, "coin": "SOL", "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        {"time": 2, "coin": "SOL", "px": "100", "sz": "5", "side": "B", "dir": "Open Long", "startPosition": "10"},
        {"time": 3, "coin": "SOL", "px": "100", "sz": "6", "side": "A", "dir": "Close Long", "startPosition": "15"},
        {"time": 4, "coin": "SOL", "px": "100", "sz": "9", "side": "A", "dir": "Close Long", "startPosition": "9"},
    ], vault="0xA")
    ev = VB.reconstruire_episodes(fills)
    assert [e["action"] for e in ev] == ["OPEN", "ADD", "REDUCE", "CLOSE"]
    assert all(e["direction"] == 1 for e in ev)                        # position longue tout du long
    assert len({e["fill_id"] for e in ev}) == 4
    assert all("oid" in e and "hash" in e and "dir" in e for e in ev)
    alpha = VB.entrees_alpha(VB.marquer_retraits(ev))
    assert [e["action"] for e in alpha] == ["OPEN", "ADD"]             # seules les entrées sont copiables


def test_marquer_retraits_pro_rata_multi_coins():
    """Un RETRAIT réduit TOUS les coins de ~la même fraction au même instant : à exclure de l'alpha."""
    fills = VB.parser_fills([
        {"time": 1, "coin": "BTC", "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        {"time": 1, "coin": "ETH", "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        {"time": 1, "coin": "SOL", "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        # retrait ~20 % simultané sur les 3 coins
        {"time": 100000, "coin": "BTC", "px": "100", "sz": "2", "side": "A", "dir": "Close Long", "startPosition": "10"},
        {"time": 100001, "coin": "ETH", "px": "100", "sz": "2", "side": "A", "dir": "Close Long", "startPosition": "10"},
        {"time": 100002, "coin": "SOL", "px": "100", "sz": "2", "side": "A", "dir": "Close Long", "startPosition": "10"},
    ], vault="0xA")
    ev = VB.marquer_retraits(VB.reconstruire_episodes(fills))
    reduces = [e for e in ev if e["action"] == "REDUCE"]
    assert reduces and all(e["retrait_probable"] for e in reduces)     # les 3 REDUCE = retrait, pas alpha


def test_auditer_couverture_troncature_et_coins_mesurables():
    # un vault au cap (troncature), un normal ; 2 coins tradés dont 1 seul avec prix (candles)
    fills = ([{"vault": "0xTRONQ", "ts_ms": 1000 + i, "coin": "OBSCURE"} for i in range(10_000)]
             + [{"vault": "0xOK", "ts_ms": 5000, "coin": "BTC"}])
    a = VB.auditer_couverture(fills, coins_tape={"BTC"})
    assert a["n_vaults"] == 2 and a["n_coins_fills"] == 2
    assert a["n_coins_mesurables"] == 1 and a["coins_mesurables"] == ["BTC"]      # OBSCURE sans prix
    assert a["part_coins_avec_prix"] == 0.5 and a["n_vaults_tronques"] == 1        # 0xTRONQ au cap 10k
    tronq = next(v for v in a["par_vault"] if v["vault"] == "0xTRONQ")
    assert tronq["tronque_probable"] is True


def test_auditer_troncature_par_debut_manquant():
    # le plus ancien fill est bien APRÈS le début demandé -> troncature (userFillsByTime a coupé l'ancien)
    fills = [{"vault": "0xA", "ts_ms": 100 * VB.MS_PAR_HEURE, "coin": "BTC"}]
    a = VB.auditer_couverture(fills, lookback_debut_ms=0)
    assert a["par_vault"][0]["tronque_probable"] is True


def test_couverture_mesuree():
    fills = VB.parser_fills([
        {"time": 1000, "coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        {"time": 1000 + VB.MS_PAR_HEURE, "coin": "BTC", "px": "60000", "sz": "1", "side": "B", "dir": "Open Long", "startPosition": "0"},
    ], vault="0xA")
    cov = VB.couverture(fills)
    assert cov["n_fills"] == 2 and cov["span_h"] == 1.0 and cov["coins"] == ["BTC", "SOL"] and cov["n_vaults"] == 1
