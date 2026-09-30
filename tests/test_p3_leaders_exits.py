"""P3: classifieur leaders + scoring par coin/PF/clusters + ExitEngine."""

from __future__ import annotations

from hl_observer.exits.exit_engine import decide_exit
from hl_observer.following.leader_behavior import (
    MARKET_MAKER, SCALPER, SWING, classify_leader, filter_copyable_leaders,
)
from hl_observer.following.leader_scoring import (
    count_consensus_clusters, market_score_multiplier, profit_factor_net,
    shortlist_by_net_pf,
)


def _fill(coin, side, action, ts_ms, **kw):
    d = {"coin": coin, "side": side, "action": action, "ts_ms": ts_ms}
    d.update(kw); return d


def test_swing_leader_is_copyable_scalper_is_not():
    # swing: ouvre puis ferme 30 min plus tard
    swing = [_fill("HYPE", "LONG", "OPEN", 0), _fill("HYPE", "LONG", "CLOSE", 1_800_000),
             _fill("BTC", "LONG", "OPEN", 2_000_000), _fill("BTC", "LONG", "CLOSE", 4_000_000)]
    b = classify_leader("0xswing", swing)
    assert b.kind == SWING and b.copyable is True
    # scalper: ouvre/ferme en 30s
    scalp = [_fill("SOL", "LONG", "OPEN", 0), _fill("SOL", "LONG", "CLOSE", 30_000),
             _fill("SOL", "LONG", "OPEN", 60_000), _fill("SOL", "LONG", "CLOSE", 90_000)]
    assert classify_leader("0xscalp", scalp).kind == SCALPER
    assert filter_copyable_leaders([b, classify_leader("0xscalp", scalp)]) == ("0xswing",)


def test_market_maker_holds_both_sides():
    mm = [_fill("BTC", "LONG", "OPEN", i * 1000) for i in range(5)] + [_fill("BTC", "SHORT", "OPEN", i * 1000 + 500) for i in range(5)]
    assert classify_leader("0xmm", mm).kind == MARKET_MAKER


def test_market_score_penalizes_weak_coin():
    trades = [
        {"wallet": "0xA", "coin": "MON", "net_pnl_usdc": -1}, {"wallet": "0xA", "coin": "MON", "net_pnl_usdc": -1},
        {"wallet": "0xA", "coin": "MON", "net_pnl_usdc": -1}, {"wallet": "0xA", "coin": "MON", "net_pnl_usdc": 1},
        {"wallet": "0xA", "coin": "BTC", "net_pnl_usdc": 1}, {"wallet": "0xA", "coin": "BTC", "net_pnl_usdc": 1},
        {"wallet": "0xA", "coin": "BTC", "net_pnl_usdc": 1}, {"wallet": "0xA", "coin": "BTC", "net_pnl_usdc": -1},
    ]
    assert market_score_multiplier(trades, "0xA", "MON") == 0.5   # 25% winrate sur MON
    assert market_score_multiplier(trades, "0xA", "BTC") == 1.0   # 75% winrate sur BTC


def test_shortlist_by_net_pf():
    trades = [
        {"wallet": "0xwin", "net_pnl_usdc": 3}, {"wallet": "0xwin", "net_pnl_usdc": 2}, {"wallet": "0xwin", "net_pnl_usdc": -1},
        {"wallet": "0xwin", "net_pnl_usdc": 2}, {"wallet": "0xwin", "net_pnl_usdc": 1},
        {"wallet": "0xlose", "net_pnl_usdc": -3}, {"wallet": "0xlose", "net_pnl_usdc": 1}, {"wallet": "0xlose", "net_pnl_usdc": -2},
        {"wallet": "0xlose", "net_pnl_usdc": -1}, {"wallet": "0xlose", "net_pnl_usdc": 1},
    ]
    assert profit_factor_net(trades, "0xwin")["profit_factor_net"] > 1
    assert shortlist_by_net_pf(trades, ["0xwin", "0xlose"], min_pf=1.0, min_trades=5) == ("0xwin",)


def test_anti_false_consensus_counts_clusters_not_wallets():
    # 3 wallets, même coin/side, même instant → 1 seul cluster (potentiellement 1 humain)
    votes = [{"wallet": f"0x{i}", "coin": "HYPE", "side": "LONG", "ts_ms": 1000 + i * 100} for i in range(3)]
    res = count_consensus_clusters(votes, time_window_ms=3_000)
    assert res["raw_wallets"] == 3
    assert res["consensus_clusters"] == 1        # vrai consensus = 1, pas 3
    assert res["inflation_ratio"] == 3.0


def test_exit_engine_partial_then_trailing_then_timestop():
    # profit atteint 1.5 ATR → TP partiel 50%
    d = decide_exit(side="LONG", entry_price=100.0, current_price=101.5, peak_price=101.5, atr_abs=1.0, age_sec=60)
    assert d.action == "PARTIAL_CLOSE" and d.fraction == 0.5 and "PARTIAL_TP" in d.reason
    # pic à 3 ATR puis recul de 0.5 ATR → momentum giveback ferme tout
    d2 = decide_exit(side="LONG", entry_price=100.0, current_price=102.5, peak_price=103.0, atr_abs=1.0, age_sec=60)
    assert d2.action == "CLOSE" and d2.reason == "MOMENTUM_GIVEBACK"
    # time-stop
    d3 = decide_exit(side="LONG", entry_price=100.0, current_price=100.2, peak_price=100.3, atr_abs=1.0, age_sec=99_999)
    assert d3.action == "CLOSE" and d3.reason == "TIME_STOP"
    # leader réduit → close
    d4 = decide_exit(side="LONG", entry_price=100.0, current_price=100.1, peak_price=100.1, atr_abs=1.0, age_sec=60, leader_prev_size=10, leader_curr_size=4)
    assert d4.action == "CLOSE" and d4.reason == "LEADER_REDUCED"
    # rien → HOLD
    d5 = decide_exit(side="LONG", entry_price=100.0, current_price=100.3, peak_price=100.4, atr_abs=1.0, age_sec=60)
    assert d5.action == "HOLD"
