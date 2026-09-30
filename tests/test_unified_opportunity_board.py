"""Contrat du tableau d'opportunités unifié cross-stratégie."""

from __future__ import annotations

from hl_observer.signals.opportunity_ranker import OpportunityInput
from hl_observer.signals.unified_opportunity_board import (
    build_opportunity_board,
    summarize_board,
)


def _opp(coin, edge, **kw):
    return OpportunityInput(coin=coin, side=kw.get("side", "LONG"), net_edge_bps=edge,
                            signal_age_ms=kw.get("age", 1000), consensus_wallets=kw.get("cons", 2),
                            liquidity_score=kw.get("liq", 0.8), leader_winrate=kw.get("lw", 0.7))


def test_best_net_edge_surfaces_regardless_of_strategy():
    board = build_opportunity_board([
        ("COPY", _opp("BTC", 20)),
        ("FUNDING_ARB", _opp("SOL", 38)),      # meilleur edge net
        ("ARBITRAGE", _opp("ETH", 12)),
    ])
    assert board[0].coin == "SOL" and board[0].strategy == "FUNDING_ARB"   # le meilleur global gagne
    assert [e.strategy for e in board].count("FUNDING_ARB") == 1
    assert board[0].power_score >= board[1].power_score >= board[2].power_score


def test_floor_failures_dropped():
    board = build_opportunity_board([
        ("COPY", _opp("BTC", 4)),              # edge < 8 -> éliminé
        ("FUNDING_ARB", _opp("SOL", 30, liq=0.1)),  # illiquide -> éliminé
        ("COPY", _opp("ETH", 25, age=99_000)),      # trop vieux -> éliminé
        ("ARBITRAGE", _opp("HYPE", 22)),       # valide
    ])
    assert [e.coin for e in board] == ["HYPE"]


def test_per_strategy_cap_prevents_monopoly():
    # 5 opportunités funding vs 1 copy ; cap 2/strat => le copy garde sa place
    tagged = [("FUNDING_ARB", _opp("C%d" % i, 30 + i)) for i in range(5)]
    tagged.append(("COPY", _opp("BTC", 20)))
    board = build_opportunity_board(tagged, max_per_strategy=2)
    n_fund = sum(1 for e in board if e.strategy == "FUNDING_ARB")
    n_copy = sum(1 for e in board if e.strategy == "COPY")
    assert n_fund == 2 and n_copy == 1     # diversifié: pas monopolisé par funding


def test_per_coin_cap_and_limit():
    tagged = [("COPY", _opp("ETH", 30)), ("FUNDING_ARB", _opp("ETH", 28)), ("ARBITRAGE", _opp("ETH", 26))]
    board = build_opportunity_board(tagged, max_per_coin=2)
    assert sum(1 for e in board if e.coin == "ETH") == 2      # cap coin respecté
    assert len(build_opportunity_board(tagged, max_per_coin=5, limit=1)) == 1


def test_summary_for_dashboard():
    board = build_opportunity_board([("COPY", _opp("BTC", 20)), ("FUNDING_ARB", _opp("SOL", 38))])
    s = summarize_board(board)
    assert s["total"] == 2 and s["top"]["coin"] == "SOL"
    assert s["by_strategy"]["FUNDING_ARB"] == 1 and s["by_strategy"]["COPY"] == 1
    assert summarize_board([])["total"] == 0                  # vide = honnête


def test_empty_input_empty_board():
    assert build_opportunity_board([]) == []
