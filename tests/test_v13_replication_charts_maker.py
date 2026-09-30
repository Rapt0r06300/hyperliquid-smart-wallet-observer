from hl_observer.copy_fidelity.balance_replication import (
    allocation_weights, build_replication_score, cosine_similarity,
)
from hl_observer.ui.charts.extended_series import (
    cumulative_brier_advantage_series, equity_by_coin, market_allocation, monthly_returns,
)
from hl_observer.signals.maker_band import band_distance_ratio, classify_tick, reprice_decision


# ---- #159 ----
def test_allocation_and_similarity():
    lead = [{"coin": "BTC", "side": "LONG", "notional_usdt": 100}, {"coin": "ETH", "side": "LONG", "notional_usdt": 100}]
    copy = [{"coin": "BTC", "side": "LONG", "notional_usdt": 50}, {"coin": "ETH", "side": "LONG", "notional_usdt": 50}]
    w = allocation_weights(lead)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    rep = build_replication_score(leader_positions=lead, copy_positions=copy)
    assert rep["similarity"] == 1.0          # same proportions -> perfect cosine
    assert rep["empty"] is False and "%" in rep["plain_summary"]


def test_replication_low_when_different():
    lead = [{"coin": "BTC", "side": "LONG", "notional_usdt": 100}]
    copy = [{"coin": "SOL", "side": "SHORT", "notional_usdt": 100}]
    assert build_replication_score(leader_positions=lead, copy_positions=copy)["similarity"] == 0.0
    assert build_replication_score(leader_positions=[], copy_positions=[])["empty"] is True


# ---- #160 ----
def test_equity_by_coin_and_allocation_and_monthly_and_brier():
    trades = [{"coin": "BTC", "close_ts_ms": 1000, "net_pnl_usdc": 5},
              {"coin": "BTC", "close_ts_ms": 2000, "net_pnl_usdc": -2},
              {"coin": "ETH", "close_ts_ms": 1500, "net_pnl_usdc": 3}]
    ebc = equity_by_coin(trades)
    assert ebc["BTC"][-1]["value"] == 3.0 and ebc["ETH"][-1]["value"] == 3.0
    alloc = market_allocation([{"coin": "BTC", "notional_usdt": 75}, {"coin": "ETH", "notional_usdt": 25}])
    assert alloc[0]["coin"] == "BTC" and alloc[0]["weight"] == 0.75
    eq = [{"time": 0, "equity": 1000}, {"time": 5*86400, "equity": 1100}]
    mr = monthly_returns(eq)
    assert mr and mr[0]["return_pct"] == 10.0
    series = cumulative_brier_advantage_series([{"time": 1, "model_p": 0.9, "outcome": 1},
                                                {"time": 2, "model_p": 0.8, "outcome": 1}])
    assert series[-1]["value"] > 0           # confident & correct beats 0.5
    assert equity_by_coin([]) == {} and monthly_returns([]) == []


# ---- #161 ----
def test_maker_band_rules_and_inventory_skip():
    assert classify_tick(0.01) == "coarse" and classify_tick(0.001) == "fine"
    assert band_distance_ratio(101, 100, 2) == 0.5
    # in band -> keep
    assert reprice_decision(price=101, mid=100, delta=2, side="BUY")["action"] == "keep"
    # too close to mid -> move out
    assert reprice_decision(price=100.2, mid=100, delta=2, side="BUY")["action"] == "move_out"
    # too far -> move in
    assert reprice_decision(price=103, mid=100, delta=2, side="BUY")["action"] == "move_in"
    # already holding -> skip (inventory-aware)
    assert reprice_decision(price=101, mid=100, delta=2, has_position=True)["action"] == "skip_inventory"
