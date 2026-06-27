"""
Tests Selection Engine v2 — scoring tiers, consensus gate, exits adaptatifs,
fills honnêtes, leaderboard builder, métriques anti-illusion.

100% mocké. Aucun appel réseau. PAPER-ONLY.
"""

from __future__ import annotations

import os
import tempfile
import time

import pytest

from hyper_smart_observer.dydx_v4.adaptive_exits import (
    TrailingState,
    build_exit_plan,
    compute_atr,
    is_time_stop_hit,
)
from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.consensus import ConsensusTracker
from hyper_smart_observer.dydx_v4.fill_simulator import (
    DATA_SOURCE_DEMO,
    simulate_market_fill,
    synthetic_orderbook,
)
from hyper_smart_observer.dydx_v4.leaderboard import (
    DydxLeaderboardBuilder,
    build_trades_from_fills,
    metrics_from_data,
)
from hyper_smart_observer.dydx_v4.metrics import (
    copy_capture_ratio,
    walk_forward_report,
    weekly_no_trade_summary,
)
from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NoTradeReason,
    PositionSide,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.selection import (
    AccountMetrics,
    SelectionTier,
    apply_tier_transition,
    classify_account,
    composite_score,
    compute_equity_metrics,
)
from hyper_smart_observer.dydx_v4.signals import DydxSignalEngine
from hyper_smart_observer.dydx_v4.ws_client import WsStatus

DAY_MS = 86_400_000
NOW_MS = int(time.time() * 1000)


def _good_metrics(**overrides) -> AccountMetrics:
    base = dict(
        address="dydx1elite", subaccount_number=0,
        closed_trades=60, winrate=0.60, profit_factor=2.0,
        total_net_pnl=500.0, single_trade_pnl_share=0.10,
        sharpe=1.8, max_drawdown_pct=12.0, history_days=90.0,
        data_confidence=0.9, data_source="REAL_INDEXER",
    )
    base.update(overrides)
    return AccountMetrics(**base)


# ─────────────────────────────────────────────────────────────────────────────
# Sélection v2 — tiers
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionTiers:
    def test_elite_metrics_classified_elite(self):
        d = classify_account(_good_metrics())
        assert d.tier == SelectionTier.ELITE
        assert d.size_multiplier == 1.0
        assert d.copyable

    def test_standard_when_history_too_short_for_elite(self):
        d = classify_account(_good_metrics(history_days=40.0, closed_trades=35))
        assert d.tier == SelectionTier.STANDARD
        assert d.size_multiplier == 0.5

    def test_watch_never_copyable(self):
        d = classify_account(_good_metrics(closed_trades=15, winrate=0.45))
        assert d.tier == SelectionTier.WATCH
        assert d.size_multiplier == 0.0
        assert not d.copyable

    def test_suspicious_winrate_capped_at_watch(self):
        """WR > 90% = pattern anormal → jamais copiable (anti-lottery/wash)."""
        d = classify_account(_good_metrics(winrate=0.95))
        assert d.tier == SelectionTier.WATCH
        assert any("WINRATE_SUSPICIOUS" in r for r in d.reasons)

    def test_demo_data_never_copyable(self):
        """Un compte issu de données démo ne doit JAMAIS être copiable."""
        d = classify_account(_good_metrics(data_source="DEMO_SYNTHETIC"))
        assert not d.copyable

    def test_negative_pnl_rejected_from_copyable_tiers(self):
        d = classify_account(_good_metrics(total_net_pnl=-10.0))
        assert d.tier in (SelectionTier.WATCH, SelectionTier.REJECTED)

    def test_concentration_blocks_elite(self):
        """Un seul trade > 50% du PnL = chance, pas du skill."""
        d = classify_account(_good_metrics(single_trade_pnl_share=0.80))
        assert d.tier != SelectionTier.ELITE

    def test_promotion_one_tier_per_refresh(self):
        # premier passage: ELITE calculé → bridé à STANDARD
        assert apply_tier_transition(None, SelectionTier.ELITE) == SelectionTier.STANDARD
        # WATCH → ELITE calculé: un seul cran → STANDARD
        assert apply_tier_transition(SelectionTier.WATCH, SelectionTier.ELITE) == SelectionTier.STANDARD
        # STANDARD → ELITE: ok
        assert apply_tier_transition(SelectionTier.STANDARD, SelectionTier.ELITE) == SelectionTier.ELITE

    def test_demotion_immediate(self):
        assert apply_tier_transition(SelectionTier.ELITE, SelectionTier.REJECTED) == SelectionTier.REJECTED

    def test_composite_score_orders_better_accounts_higher(self):
        good = composite_score(_good_metrics())
        bad = composite_score(_good_metrics(sharpe=0.1, profit_factor=1.1, winrate=0.42,
                                            max_drawdown_pct=45.0, history_days=10.0))
        assert good > bad


class TestEquityMetrics:
    def test_rising_curve_positive_sharpe_low_dd(self):
        points = [(NOW_MS - (90 - i) * DAY_MS, 1000.0 + i * 5 + (i % 7)) for i in range(91)]
        m = compute_equity_metrics(points)
        assert m.sharpe > 1.0
        assert m.max_drawdown_pct < 5.0
        assert 85 <= m.history_days <= 91

    def test_drawdown_detected(self):
        points = (
            [(NOW_MS - (60 - i) * DAY_MS, 1000.0 + i * 10) for i in range(30)]
            + [(NOW_MS - (30 - i) * DAY_MS, 1290.0 - i * 20) for i in range(20)]
        )
        m = compute_equity_metrics(points)
        assert m.max_drawdown_pct > 20.0

    def test_empty_curve_safe(self):
        m = compute_equity_metrics([])
        assert m.sharpe == 0.0 and m.history_days == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Consensus
# ─────────────────────────────────────────────────────────────────────────────
class TestConsensusTracker:
    def test_single_wallet_not_met(self):
        t = ConsensusTracker(min_wallets=2, window_ms=600_000)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS)
        assert not t.check("ETH-USD", "LONG", NOW_MS).met

    def test_two_wallets_met(self):
        t = ConsensusTracker(min_wallets=2, window_ms=600_000)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS - 1000)
        t.record_open("b/0", "ETH-USD", "LONG", NOW_MS)
        res = t.check("ETH-USD", "LONG", NOW_MS)
        assert res.met and res.distinct_accounts == 2

    def test_same_wallet_twice_counts_once(self):
        t = ConsensusTracker(min_wallets=2)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS - 1000)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS)
        assert not t.check("ETH-USD", "LONG", NOW_MS).met

    def test_opposite_sides_do_not_mix(self):
        t = ConsensusTracker(min_wallets=2)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS)
        t.record_open("b/0", "ETH-USD", "SHORT", NOW_MS)
        assert not t.check("ETH-USD", "LONG", NOW_MS).met

    def test_window_expiry(self):
        t = ConsensusTracker(min_wallets=2, window_ms=10_000)
        t.record_open("a/0", "ETH-USD", "LONG", NOW_MS - 60_000)  # trop vieux
        t.record_open("b/0", "ETH-USD", "LONG", NOW_MS)
        assert not t.check("ETH-USD", "LONG", NOW_MS).met


class TestConsensusGateInEngine:
    def _engine(self) -> DydxSignalEngine:
        cfg = DydxV4Config(consensus_required=True, consensus_min_wallets=2)
        eng = DydxSignalEngine(cfg, consensus=ConsensusTracker(2, 600_000))
        eng.update_shortlist({"dydx1aaa/0", "dydx1bbb/0"})
        eng.update_ws_status(WsStatus.CONNECTED)
        return eng

    def _delta(self, eng, addr, lifecycle=LifecycleEvent.OPEN):
        return eng.evaluate_delta(
            account_address=addr, subaccount_number=0,
            market_id="ETH-USD", side=PositionSide.LONG,
            lifecycle=lifecycle, size=1.0, price=3000.0,
            signal_age_ms=500, simulation_mode=SimulationMode.LIVE,
        )

    def test_first_open_refused_consensus(self):
        eng = self._engine()
        cand, dec = self._delta(eng, "dydx1aaa")
        assert cand is None
        assert dec.reason == NoTradeReason.CONSENSUS_NOT_REACHED

    def test_second_wallet_unlocks_signal(self):
        eng = self._engine()
        self._delta(eng, "dydx1aaa")
        cand, dec = self._delta(eng, "dydx1bbb")
        # le consensus est atteint → le refus éventuel ne doit PAS être le consensus
        if dec is not None:
            assert dec.reason != NoTradeReason.CONSENSUS_NOT_REACHED
        else:
            assert cand is not None

    def test_close_never_blocked_by_consensus(self):
        """On doit TOUJOURS pouvoir sortir: CLOSE bypasse le consensus."""
        eng = self._engine()
        cand, dec = self._delta(eng, "dydx1aaa", lifecycle=LifecycleEvent.CLOSE)
        if dec is not None:
            assert dec.reason != NoTradeReason.CONSENSUS_NOT_REACHED

    def test_engine_without_tracker_unchanged(self):
        """Sans tracker → comportement v1 (pas de gate consensus)."""
        cfg = DydxV4Config()
        eng = DydxSignalEngine(cfg)
        eng.update_shortlist({"dydx1aaa/0"})
        eng.update_ws_status(WsStatus.CONNECTED)
        cand, dec = eng.evaluate_delta(
            account_address="dydx1aaa", subaccount_number=0,
            market_id="ETH-USD", side=PositionSide.LONG,
            lifecycle=LifecycleEvent.OPEN, size=1.0, price=3000.0,
            signal_age_ms=500,
        )
        if dec is not None:
            assert dec.reason != NoTradeReason.CONSENSUS_NOT_REACHED


# ─────────────────────────────────────────────────────────────────────────────
# Exits adaptatifs
# ─────────────────────────────────────────────────────────────────────────────
def _candles(n=40, base=100.0, rng=2.0):
    out = []
    for i in range(n):
        out.append({
            "startedAt": f"2026-06-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            "high": str(base + rng), "low": str(base - rng), "close": str(base),
        })
    return out


class TestAdaptiveExits:
    def test_atr_computed(self):
        atr = compute_atr(_candles(), period=14)
        assert 3.0 < atr < 5.0  # TR = high-low = 4

    def test_atr_insufficient_data_returns_zero(self):
        assert compute_atr(_candles(n=5), period=14) == 0.0

    def test_plan_long_atr(self):
        plan = build_exit_plan(100.0, "LONG", atr=2.0)
        assert plan.method == "ATR"
        assert plan.stop_price == pytest.approx(97.0)    # -1.5×ATR
        assert plan.take_profit_price == pytest.approx(103.0)  # first partial TP: +1.5x ATR
        assert plan.trail_distance == pytest.approx(2.0)

    def test_plan_short_atr(self):
        plan = build_exit_plan(100.0, "SHORT", atr=2.0)
        assert plan.stop_price == pytest.approx(103.0)
        assert plan.take_profit_price == pytest.approx(97.0)

    def test_fallback_fixed_pct_preserved(self):
        plan = build_exit_plan(100.0, "LONG", atr=0.0,
                               fallback_stop_pct=1.5, fallback_tp_pct=2.5)
        assert plan.method == "FIXED_PCT_FALLBACK"
        assert plan.stop_price == pytest.approx(98.5)
        assert plan.take_profit_price == pytest.approx(102.5)

    def test_funding_adverse_halves_holding(self):
        normal = build_exit_plan(100.0, "LONG", atr=2.0, max_holding_hours=48.0,
                                 funding_rate_hourly=0.0)
        adverse = build_exit_plan(100.0, "LONG", atr=2.0, max_holding_hours=48.0,
                                  funding_rate_hourly=0.0005)
        assert adverse.max_holding_ms == normal.max_holding_ms // 2

    def test_trailing_arms_then_triggers(self):
        ts = TrailingState(side="LONG", trail_distance=2.0, trail_arm_price=102.0)
        assert ts.update(101.0) is None      # pas armé
        assert ts.update(103.0) is None      # armé, best=103, stop=101
        assert ts.armed
        assert ts.update(104.0) is None      # best=104, stop=102
        trigger = ts.update(101.9)           # retrace sous le stop
        assert trigger is not None and trigger == pytest.approx(102.0)

    def test_trailing_tightens_after_two_atr_profit(self):
        ts = TrailingState(
            side="LONG",
            trail_distance=4.0,
            trail_arm_price=102.0,
            entry_price=100.0,
            atr=2.0,
            trail_tighten_distance=2.0,
        )
        assert ts.update(105.0) is None
        assert ts.armed
        assert ts.trail_distance == pytest.approx(2.0)
        assert ts.trail_stop_price == pytest.approx(103.0)

    def test_momentum_pullback_from_peak_triggers_exit(self):
        ts = TrailingState(
            side="LONG",
            trail_distance=4.0,
            trail_arm_price=102.0,
            entry_price=100.0,
            atr=2.0,
            trail_tighten_distance=2.0,
            momentum_pullback_distance=1.0,
        )
        assert ts.update(105.0) is None
        trigger = ts.update(103.9)
        assert trigger == pytest.approx(104.0)

    def test_short_momentum_pullback_from_peak_triggers_exit(self):
        ts = TrailingState(
            side="SHORT",
            trail_distance=4.0,
            trail_arm_price=98.0,
            entry_price=100.0,
            atr=2.0,
            trail_tighten_distance=2.0,
            momentum_pullback_distance=1.0,
        )
        assert ts.update(95.0) is None
        assert ts.trail_distance == pytest.approx(2.0)
        trigger = ts.update(96.1)
        assert trigger == pytest.approx(96.0)

    def test_time_stop(self):
        assert is_time_stop_hit(NOW_MS - 10_000, NOW_MS, 5_000)
        assert not is_time_stop_hit(NOW_MS - 1_000, NOW_MS, 5_000)
        assert not is_time_stop_hit(NOW_MS - 99_000, NOW_MS, 0)  # désactivé


# ─────────────────────────────────────────────────────────────────────────────
# Fills honnêtes
# ─────────────────────────────────────────────────────────────────────────────
def _book(mid=100.0, spread_bps=10.0, level_size=10.0, levels=5):
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half * (1 + i)), "size": str(level_size)} for i in range(levels)],
        "asks": [{"price": str(mid + half * (1 + i)), "size": str(level_size)} for i in range(levels)],
    }


class TestHonestFills:
    def test_buy_never_at_mid(self):
        res = simulate_market_fill(_book(), "BUY", 200.0)
        assert res.ok
        assert res.fill_price > res.mid_price  # spread traversé + latence
        assert res.slippage_bps > 0

    def test_sell_below_mid(self):
        res = simulate_market_fill(_book(), "SELL", 200.0)
        assert res.ok and res.fill_price < res.mid_price

    def test_insufficient_depth_refused(self):
        # profondeur totale ≈ 5 × 10 × ~100 = ~5000; 10% = 500 → 600 refusé
        res = simulate_market_fill(_book(), "BUY", 600.0, max_participation=0.10)
        assert not res.ok
        assert "INSUFFICIENT_DEPTH" in res.reason

    def test_big_order_walks_book(self):
        small = simulate_market_fill(_book(), "BUY", 100.0, max_participation=1.0)
        big = simulate_market_fill(_book(), "BUY", 3000.0, max_participation=1.0)
        assert big.ok and small.ok
        assert big.fill_price > small.fill_price  # impact de profondeur
        assert big.levels_consumed > small.levels_consumed

    def test_empty_book_refused(self):
        res = simulate_market_fill({"bids": [], "asks": []}, "BUY", 100.0)
        assert not res.ok and res.reason == "NO_ORDERBOOK"

    def test_demo_source_propagated(self):
        book = synthetic_orderbook(100.0)
        res = simulate_market_fill(book, "BUY", 100.0, data_source=DATA_SOURCE_DEMO)
        assert res.ok and res.data_source == DATA_SOURCE_DEMO


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard builder
# ─────────────────────────────────────────────────────────────────────────────
def _winning_fills(market: str, n_win: int, n_loss: int, start_day: int = 0):
    """Génère des paires BUY/SELL (LONG) gagnantes/perdantes."""
    fills = []
    day = start_day
    for i in range(n_win + n_loss):
        win = i < n_win
        t_open = f"2026-{3 + day // 28:02d}-{(day % 28) + 1:02d}T10:00:00Z"
        t_close = f"2026-{3 + day // 28:02d}-{(day % 28) + 1:02d}T16:00:00Z"
        fills.append({"market": market, "side": "BUY", "price": "100.0",
                      "size": "1.0", "fee": "0.01", "createdAt": t_open})
        fills.append({"market": market, "side": "SELL",
                      "price": "101.0" if win else "99.5",
                      "size": "1.0", "fee": "0.01", "createdAt": t_close})
        day += 1
    return fills


class FakeRest:
    """REST Indexer mocké — aucun réseau."""

    def __init__(self, data: dict):
        self.data = data  # address -> {"fills": [...], "equity": [...]}

    def get_historical_pnl(self, address: str, subaccount_number: int = 0, **kw):
        eq = self.data.get(address, {}).get("equity", [])
        return {"historicalPnl": [
            {"equity": str(v), "totalPnl": "0",
             "createdAt": f"2026-{3 + d // 28:02d}-{(d % 28) + 1:02d}T00:00:00Z"}
            for d, v in eq
        ]}

    def paginate_fills(self, address: str, subaccount_number: int = 0, **kw):
        return self.data.get(address, {}).get("fills", [])


class TestLeaderboardBuilder:
    def _fake(self):
        good_equity = [(d, 1000.0 + d * 5 + (d % 5)) for d in range(91)]
        bad_equity = [(d, 1000.0 - d * 8) for d in range(40)]
        return FakeRest({
            "dydx1good": {
                "fills": _winning_fills("ETH-USD", 18, 12) + _winning_fills("BTC-USD", 19, 11, start_day=30),
                "equity": good_equity,
            },
            "dydx1bad": {
                "fills": _winning_fills("ETH-USD", 3, 12),
                "equity": bad_equity,
            },
        })

    def test_build_trades_from_fills(self):
        trades = build_trades_from_fills(_winning_fills("ETH-USD", 2, 1))
        assert len(trades) == 3
        wins = [t for t in trades if t["pnl_net"] > 0]
        assert len(wins) == 2
        assert all(t["fees"] > 0 for t in trades)

    def test_metrics_from_data_realistic(self):
        rest = self._fake()
        m = metrics_from_data(
            "dydx1good", 0,
            rest.paginate_fills("dydx1good"),
            [(NOW_MS - (90 - d) * DAY_MS, 1000.0 + d * 5) for d in range(91)],
        )
        assert m.closed_trades == 60
        assert 0.55 <= m.winrate <= 0.65
        assert m.profit_factor > 1.5
        assert m.sharpe > 1.0
        assert m.data_confidence >= 0.7

    def test_build_ranks_good_above_bad_and_demotes_bad(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "lb.sqlite3")
            builder = DydxLeaderboardBuilder(
                rest=self._fake(), cosmos=None, db_path=db, rate_limit_sleep_s=0,
            )
            res1 = builder.build(extra_addresses=[("dydx1good", 0), ("dydx1bad", 0)])
            assert res1.candidates_evaluated == 2
            by_addr = {e.address: e for e in res1.entries}
            assert by_addr["dydx1good"].rank < by_addr["dydx1bad"].rank
            # premier passage: jamais ELITE direct
            assert by_addr["dydx1good"].tier == SelectionTier.STANDARD
            assert not by_addr["dydx1bad"].copyable

            # deuxième run: promotion STANDARD → ELITE possible
            res2 = builder.build(extra_addresses=[("dydx1good", 0), ("dydx1bad", 0)])
            by_addr2 = {e.address: e for e in res2.entries}
            assert by_addr2["dydx1good"].tier == SelectionTier.ELITE
            assert any("dydx1good" in p for p in res2.promotions)

    def test_export_shortlist_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "lb.sqlite3")
            out = os.path.join(tmp, "shortlist.json")
            builder = DydxLeaderboardBuilder(
                rest=self._fake(), cosmos=None, db_path=db, rate_limit_sleep_s=0,
            )
            res = builder.build(extra_addresses=[("dydx1good", 0)])
            builder.export_shortlist_json(res, out)
            import json
            payload = json.load(open(out))
            assert payload["shortlist"], "shortlist vide"
            assert payload["disclaimer"]
            assert all(e["tier"] in ("ELITE", "STANDARD") for e in payload["shortlist"])


# ─────────────────────────────────────────────────────────────────────────────
# Métriques anti-illusion
# ─────────────────────────────────────────────────────────────────────────────
class TestMetrics:
    def test_copy_capture_ratio(self):
        ours = [
            {"market": "ETH-USD", "side": "LONG", "opened_at_ms": NOW_MS, "pnl_net": 3.0},
            {"market": "BTC-USD", "side": "SHORT", "opened_at_ms": NOW_MS, "pnl_net": 1.0},
        ]
        leader = [
            {"market": "ETH-USD", "side": "LONG", "opened_at_ms": NOW_MS - 5_000, "pnl_net": 10.0},
            {"market": "BTC-USD", "side": "SHORT", "opened_at_ms": NOW_MS - 3_000, "pnl_net": 6.0},
        ]
        rep = copy_capture_ratio(ours, leader)
        assert rep.matched_trades == 2
        assert rep.capture_ratio == pytest.approx(4.0 / 16.0)

    def test_capture_ratio_none_when_leader_negative(self):
        rep = copy_capture_ratio(
            [{"market": "ETH-USD", "side": "LONG", "opened_at_ms": NOW_MS, "pnl_net": 1.0}],
            [{"market": "ETH-USD", "side": "LONG", "opened_at_ms": NOW_MS, "pnl_net": -5.0}],
        )
        assert rep.capture_ratio is None  # non interprétable, pas de fausse précision

    def test_walk_forward_windows(self):
        trades = [
            {"closed_at_ms": NOW_MS - (40 - i) * DAY_MS, "pnl_net": 1.0 if i % 3 else -0.5}
            for i in range(40)
        ]
        rep = walk_forward_report(trades, n_windows=4)
        assert len(rep.windows) == 4
        assert sum(w.trades for w in rep.windows) == 40
        assert 0.0 <= rep.stability <= 1.0

    def test_weekly_no_trade_summary(self):
        decisions = [
            {"reason": "CONSENSUS_NOT_REACHED", "timestamp_ms": NOW_MS - DAY_MS},
            {"reason": "CONSENSUS_NOT_REACHED", "timestamp_ms": NOW_MS - 2 * DAY_MS},
            {"reason": "STALE_SIGNAL", "timestamp_ms": NOW_MS - 30 * DAY_MS},  # hors fenêtre
        ]
        s = weekly_no_trade_summary(decisions, NOW_MS)
        assert s["total_refused"] == 2
        assert s["by_reason"]["CONSENSUS_NOT_REACHED"] == 2
