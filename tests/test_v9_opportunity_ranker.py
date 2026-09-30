from hl_observer.signals.opportunity_ranker import (
    OpportunityInput,
    RankerConfig,
    power_score,
    rank_opportunities,
)


def _opp(coin="ETH", side="LONG", edge=20, age=2000, cons=2, liq=0.8, bias=0.0, lw=None):
    return OpportunityInput(coin=coin, side=side, net_edge_bps=edge, signal_age_ms=age,
                            consensus_wallets=cons, liquidity_score=liq,
                            directional_bias_bps=bias, leader_winrate=lw)


def test_floor_low_edge_scores_zero():
    assert power_score(_opp(edge=5), RankerConfig(min_net_edge_bps=8)) == 0.0


def test_floor_illiquid_scores_zero():
    assert power_score(_opp(liq=0.1)) == 0.0


def test_floor_stale_scores_zero():
    assert power_score(_opp(age=999_999)) == 0.0


def test_higher_edge_higher_score():
    lo = power_score(_opp(edge=10))
    hi = power_score(_opp(edge=35))
    assert hi > lo > 0


def test_consensus_and_trend_help():
    base = power_score(_opp(cons=1, bias=0.0))
    better = power_score(_opp(cons=4, bias=10.0))
    assert better > base


def test_smart_money_leader_helps():
    unknown = power_score(_opp(lw=None))
    strong = power_score(_opp(lw=0.9))
    assert strong > unknown


def test_ranking_sorts_by_power():
    cands = [_opp(coin="A", edge=10), _opp(coin="B", edge=35), _opp(coin="C", edge=20)]
    ranked = rank_opportunities(cands)
    assert [r.coin for r in ranked] == ["B", "C", "A"]


def test_per_coin_cap_diversifies():
    # 5 strong ETH signals + 1 SOL -> cap keeps at most 2 ETH, so SOL survives
    cands = [_opp(coin="ETH", edge=30) for _ in range(5)] + [_opp(coin="SOL", edge=15)]
    ranked = rank_opportunities(cands, RankerConfig(max_per_coin=2))
    coins = [r.coin for r in ranked]
    assert coins.count("ETH") == 2
    assert "SOL" in coins


def test_limit_caps_total():
    cands = [_opp(coin=f"C{i}", edge=20) for i in range(10)]
    ranked = rank_opportunities(cands, limit=3)
    assert len(ranked) == 3


def test_floor_failures_dropped_from_ranking():
    cands = [_opp(coin="A", edge=20), _opp(coin="B", edge=2), _opp(coin="C", liq=0.05)]
    ranked = rank_opportunities(cands)
    assert [r.coin for r in ranked] == ["A"]
