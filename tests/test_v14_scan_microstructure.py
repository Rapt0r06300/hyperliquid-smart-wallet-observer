"""V14 #171-#180 — WS audit, market ranking, leaderboard robustness, multi-source merge,
consensus window, rate-limit semaphore, proxy health, depth/spread gate, microstructure
shadow, decision cadence. Pure / paper-only / read-only."""

from __future__ import annotations

import pytest

# #171
from hl_observer.realtime.ws_subscription_audit import (
    BackoffPolicy, backpressure_decision, detect_sequence_gaps, audit_ws_health,
)

def test_ws_backoff_bounded_and_backpressure():
    p = BackoffPolicy()
    assert p.next_delay_s(0) == 1
    assert p.next_delay_s(100) == 30           # capped at last step
    assert backpressure_decision(queue_len=10, max_len=10) == "DROP_OLDEST"
    assert backpressure_decision(queue_len=9, max_len=10) == "WARN"
    assert backpressure_decision(queue_len=1, max_len=10) == "OK"

def test_ws_sequence_gaps_and_audit():
    gaps, missing = detect_sequence_gaps([1, 2, 5, 6, 10])
    assert missing == 5  # 3,4 then 7,8,9
    assert len(gaps) == 2
    a = audit_ws_health(reconnects=1, backpressure_warns=0, backpressure_drops=0,
                        seqs_by_channel={"trades": [1, 2, 3]}, last_msg_age_ms=100)
    assert a.status in {"RECOVERED", "OK"}
    stale = audit_ws_health(reconnects=0, backpressure_warns=0, backpressure_drops=0,
                            last_msg_age_ms=99_999)
    assert stale.status == "STALE_NO_RECENT_MESSAGES"

# #172
from hl_observer.markets.market_discovery_ranking import MarketStat, rank_markets_by_liquidity

def test_market_ranking_liquidity_first():
    stats = [
        MarketStat("BTC", 5_000_000, 0.9, 5),
        MarketStat("DEADCOIN", 1_000, 0.05, 1200),
        MarketStat("ETH", 3_000_000, 0.8, 8),
    ]
    r = rank_markets_by_liquidity(stats, min_volume_usd=50_000, min_liquidity_score=0.22, top_n=10)
    coins = [m.coin for m in r.shortlist]
    assert coins == ["BTC", "ETH"]           # liquid first, illiquid excluded
    assert any(c == "DEADCOIN" for c, _ in r.excluded)

# #173
from hl_observer.wallets.leaderboard_robustness import LeaderRow, SmartMoneyThresholds, apply_smart_money_filter

def test_leaderboard_robustness_filters_and_dedupes():
    rows = [
        LeaderRow("0x" + "a" * 40, 100_000, 0.5, 0.6, 50, 5),
        LeaderRow("0x" + "a" * 40, 120_000, 0.5, 0.6, 50, 5),   # dup -> keep best PnL
        LeaderRow("BADADDR", 999_999, 9, 9, 9, 1),               # invalid
        LeaderRow("0x" + "b" * 40, 1_000, 0.5, 0.6, 50, 5),      # PnL too low
    ]
    kept, rejected = apply_smart_money_filter(rows, SmartMoneyThresholds())
    assert len(kept) == 1 and kept[0].pnl_usd == 120_000
    reasons = {r for _, r in rejected}
    assert "BAD_ADDRESS" in reasons and "PNL_BELOW_MIN" in reasons

# #174
from hl_observer.wallets.multi_source_merge import WalletRef, merge_wallet_sources

def test_multi_source_merge_provenance_and_confidence():
    a = "0x" + "1" * 40
    refs = [
        WalletRef(a, "explorer", 0.6, 100),
        WalletRef(a, "leaderboard", 0.7, 200),
        WalletRef(a.upper(), "ws_firehose", 0.5, 300),   # same addr, different case
        WalletRef("0x" + "2" * 40, "explorer", 0.9, 50),
    ]
    merged = merge_wallet_sources(refs)
    top = merged[0]
    assert top.address == a and top.n_sources == 3       # 3-source corroboration ranks first
    assert top.confidence > 0.7                          # boosted above best_score 0.7
    assert top.last_seen_ms == 300

# #175
from hl_observer.signals.consensus_window import (
    ConsensusWindowConfig, consensus_window_status, apply_consensus_window_promotion,
    ACCEPT_MARKER, REJECT_REASON as CW_REJECT,
)

def test_consensus_window_status_and_promotion():
    hot = consensus_window_status(first_seen_ms=1000, now_ms=3000)   # age 2000 <= 4000
    assert hot.in_hot_window and hot.status == "HOT"
    stale = consensus_window_status(first_seen_ms=0, now_ms=20_000)
    assert stale.status == "STALE" and stale.in_window is False
    assert apply_consensus_window_promotion(score_reason=ACCEPT_MARKER, in_window=False, authoritative=True) == CW_REJECT
    assert apply_consensus_window_promotion(score_reason=ACCEPT_MARKER, in_window=None, authoritative=True) == ACCEPT_MARKER
    assert apply_consensus_window_promotion(score_reason=ACCEPT_MARKER, in_window=False, authoritative=False) == ACCEPT_MARKER

# #176
from hl_observer.scanner.rate_limit_semaphore import RateLimitConfig, evaluate_rate_limit, weight_budget_check, RateLimiterState

def test_rate_limit_window_and_weight():
    cfg = RateLimitConfig(max_requests=3, window_s=10)
    v = evaluate_rate_limit([1.0, 2.0, 3.0], now_s=5.0, config=cfg)
    assert v.allowed is False and v.reason == "RATE_LIMITED" and v.retry_after_s > 0
    v2 = evaluate_rate_limit([1.0], now_s=5.0, config=cfg)
    assert v2.allowed and v2.remaining == 2
    ok, remaining = weight_budget_check(used_weight=1100, request_weight=50, max_weight=1200)
    assert ok and remaining == 50
    assert weight_budget_check(used_weight=1180, request_weight=50, max_weight=1200)[0] is False
    st = RateLimiterState(cfg)
    assert st.try_acquire(100.0).allowed

# #177
from hl_observer.collection.proxy_health import ProxyStat, summarize_proxy_pool

def test_proxy_health_rotation_and_fallback():
    stats = [
        ProxyStat("p1", ok=90, fail=10),
        ProxyStat("p2", ok=10, fail=90),    # unhealthy
        ProxyStat("p3", ok=80, fail=5, banned=True),  # banned
    ]
    s = summarize_proxy_pool(stats)
    assert s.healthy == 1 and s.next_proxy_id == "p1" and s.fallback == "PROXY"
    all_bad = summarize_proxy_pool([ProxyStat("p2", ok=1, fail=99)])
    assert all_bad.fallback == "DIRECT" and all_bad.next_proxy_id is None

# #178
from hl_observer.signals.depth_spread_gate import (
    DepthSpreadConfig, spread_tier, depth_spread_gate, apply_depth_spread_promotion,
    REJECT_REASON as DS_REJECT,
)

def test_depth_spread_gate_and_tiers():
    assert spread_tier(100) == "OK" and spread_tier(500) == "DEGRADED" and spread_tier(900) == "BAD"
    good = depth_spread_gate(top1_usd=100, top3_usd=300, bid_depth_usd=5000, ask_depth_usd=5000,
                             side="LONG", needed_usd=40, spread_bps=50)
    assert good.ok and good.spread_tier == "OK"
    thin = depth_spread_gate(top1_usd=5, top3_usd=300, bid_depth_usd=5000, ask_depth_usd=5000,
                             side="LONG", needed_usd=40, spread_bps=50)
    assert thin.ok is False and thin.reason == "TOP1_TOO_THIN"
    assert apply_depth_spread_promotion(score_reason=ACCEPT_MARKER, gate_ok=False, authoritative=True) == DS_REJECT
    assert apply_depth_spread_promotion(score_reason=ACCEPT_MARKER, gate_ok=None, authoritative=True) == ACCEPT_MARKER

# #179
from hl_observer.signals.entry_microstructure_shadow import eat_flow_ratio, entry_microstructure_shadow

def test_microstructure_shadow_alignment():
    assert eat_flow_ratio(80, 20) == 0.6
    m = entry_microstructure_shadow(bid_sizes=[10, 10], ask_sizes=[1, 1],
                                    aggressive_buy_usd=90, aggressive_sell_usd=10, side="LONG")
    assert m.micro_side == "LONG" and m.aligned is True and m.context_only is True
    m2 = entry_microstructure_shadow(bid_sizes=[1], ask_sizes=[10],
                                     aggressive_buy_usd=5, aggressive_sell_usd=95, side="LONG")
    assert m2.aligned is False

# #180
from hl_observer.scanner.decision_cadence import CadenceConfig, cadence_decision

def test_decision_cadence_cooldown_and_budgets():
    cfg = CadenceConfig(cooldown_s=2.0, window_s=10.0, max_decisions_per_window=3, max_notional_per_window_usd=300)
    cold = cadence_decision(now_s=100.5, last_decision_s=100.0, recent_decision_times_s=[100.0],
                            window_notional_usd=40, intended_notional_usd=40, config=cfg)
    assert cold.allowed is False and cold.reason == "COOLDOWN_ACTIVE"
    full = cadence_decision(now_s=110.0, last_decision_s=100.0, recent_decision_times_s=[103, 104, 105],
                            window_notional_usd=40, intended_notional_usd=40, config=cfg)
    assert full.allowed is False and full.reason == "WINDOW_COUNT_BUDGET_EXCEEDED"
    over = cadence_decision(now_s=110.0, last_decision_s=100.0, recent_decision_times_s=[105],
                            window_notional_usd=280, intended_notional_usd=40, config=cfg)
    assert over.allowed is False and over.reason == "WINDOW_NOTIONAL_BUDGET_EXCEEDED"
    ok = cadence_decision(now_s=110.0, last_decision_s=100.0, recent_decision_times_s=[105],
                          window_notional_usd=40, intended_notional_usd=40, config=cfg)
    assert ok.allowed is True
