"""V26 — Tests des lots L3 (unstuck), L4 (halt gradué), L5 (protections), L6 (Kelly leader),
L7 (budget tier + WE/WEL), L8 (qualité marché), L9 (A/B replay) + reliquat (coûts carnet).

100 % simulation : fixtures synthétiques (TEST_FIXTURE), aucun ordre réel, aucune I/O réseau.
"""

from __future__ import annotations

import pytest

NOW_MS = 10_000_000


@pytest.fixture(autouse=True)
def _clean_state():
    from hl_observer.collection import l2_snapshot_cache as l2c
    from hl_observer.risk.graded_halt import DEFAULT_GRADED_HALT
    from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK
    from hl_observer.signals.market_quality_score import DEFAULT_MARKET_QUALITY_BOOK
    from hl_observer.signals.v26_entry_vetos import DEFAULT_EDGE_TREND_RECORDER

    for reset in (DEFAULT_PROTECTIONS_BOOK.clear, DEFAULT_KELLY_LEADER_BOOK.clear,
                  DEFAULT_MARKET_QUALITY_BOOK.clear, DEFAULT_GRADED_HALT.reset,
                  DEFAULT_EDGE_TREND_RECORDER.clear, l2c.clear):
        reset()
    yield
    for reset in (DEFAULT_PROTECTIONS_BOOK.clear, DEFAULT_KELLY_LEADER_BOOK.clear,
                  DEFAULT_MARKET_QUALITY_BOOK.clear, DEFAULT_GRADED_HALT.reset,
                  DEFAULT_EDGE_TREND_RECORDER.clear, l2c.clear):
        reset()


def _close_event(coin="BTC", pnl=-1.0, at_ms=NOW_MS, stop=True, wallet="0xabc", notional=50.0):
    return {
        "coin": coin, "paper_action_type": "CLOSE",
        "exit_method": "SLTP_STOP_LOSS" if stop else "SLTP_TAKE_PROFIT",
        "estimated_net_pnl_usdc": pnl, "observed_at_ms": at_ms,
        "matched_position_key": f"{wallet}|{coin}|LONG", "notional_closed_usdt": notional,
    }


# ================================================================ L5 protections

def test_l5_stoploss_guard_blocks_after_n_stops():
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK as book

    events = [_close_event(pnl=-2.0, at_ms=NOW_MS - i * 60_000) for i in range(4)]
    assert book.update_from_ledger_events(events) == 4
    v = book.entry_verdict("BTC", NOW_MS, env={"HYPERSMART_V26_SG_TRADE_LIMIT": "4"})
    assert v.blocked and v.reason == "STOPLOSS_GUARD_ACTIVE"
    # marché différent (per-market défaut) : pas bloqué par le guard, ni par le DD (< seuil)
    v2 = book.stoploss_guard("ETH", NOW_MS, env=None)
    assert v2.blocked is False


def test_l5_low_profit_market_blacklists():
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK as book

    book.update_from_ledger_events([
        _close_event(coin="DOGE", pnl=-3.0, stop=False, at_ms=NOW_MS - 100_000),
        _close_event(coin="DOGE", pnl=-2.0, stop=False, at_ms=NOW_MS - 50_000),
    ])
    v = book.low_profit_market("DOGE", NOW_MS)
    assert v.blocked and v.reason == "MARKET_LOW_PROFIT_BLOCKED"
    assert book.low_profit_market("BTC", NOW_MS).blocked is False


def test_l5_windowed_drawdown_halts_globally():
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK as book

    book.update_from_ledger_events([_close_event(pnl=-8.0, stop=False, at_ms=NOW_MS - 10_000),
                                    _close_event(pnl=-9.0, stop=False, at_ms=NOW_MS - 5_000)])
    v = book.windowed_drawdown(NOW_MS, env={"HYPERSMART_V26_DD_MAX_LOSS_USD": "15"})
    assert v.blocked and v.reason == "WINDOWED_DRAWDOWN_HALT"


def test_l5_empty_book_never_blocks():
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK as book

    assert book.entry_verdict("BTC", NOW_MS).blocked is False


# ================================================================ L3 auto-unstuck

def _stuck_positions():
    return {
        "w|BTC|LONG": {"size": 1.0, "avg_price": 100.0, "entry_costs": 0.0, "opened_at_ms": NOW_MS - 4_000_000, "coin": "BTC"},
        "w|ETH|LONG": {"size": 1.0, "avg_price": 100.0, "entry_costs": 0.0, "opened_at_ms": NOW_MS - 4_000_000, "coin": "ETH"},
    }


def test_l3_flag_off_is_noop():
    from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck

    p = _stuck_positions()
    out = apply_auto_unstuck(p, [], {"BTC": 98.0, "ETH": 97.0}, now_ms=NOW_MS, env={})
    assert out == [] and p["w|BTC|LONG"]["size"] == 1.0


def test_l3_least_underwater_first_partial_close():
    from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck

    p = _stuck_positions()
    ledger: list[dict] = []
    env = {"HYPERSMART_V26_AUTO_UNSTUCK": "1"}
    # BTC -200 bps, ETH -300 bps => BTC (moins sous l'eau) traité d'abord
    out = apply_auto_unstuck(p, ledger, {"BTC": 98.0, "ETH": 97.0}, now_ms=NOW_MS, env=env)
    acts = [a for a in out if a.get("action") == "UNSTUCK_PARTIAL_CLOSE"]
    assert len(acts) == 1 and acts[0]["coin"] == "BTC"
    assert p["w|BTC|LONG"]["size"] == pytest.approx(0.9)          # 10% clos
    assert ledger and ledger[0]["exit_method"] == "UNSTUCK_PARTIAL"
    assert ledger[0]["estimated_net_pnl_usdc"] < 0                 # perte réalisée assumée
    assert ledger[0]["size_after"] == pytest.approx(0.9)


def test_l3_budget_exhausted_stops_unstucking():
    from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck, unstuck_budget_spent_usd

    ledger = [{
        "exit_method": "UNSTUCK_PARTIAL", "estimated_net_pnl_usdc": -10.0,
        "observed_at_ms": NOW_MS - 60_000, "paper_action_type": "CLOSE", "coin": "BTC",
    }]
    assert unstuck_budget_spent_usd(ledger, NOW_MS, 1440.0) == 10.0
    p = _stuck_positions()
    env = {"HYPERSMART_V26_AUTO_UNSTUCK": "1", "HYPERSMART_V26_UNSTUCK_BUDGET_USD": "10"}
    out = apply_auto_unstuck(p, ledger, {"BTC": 98.0, "ETH": 97.0}, now_ms=NOW_MS, env=env)
    assert out and out[0]["reason"] == "BUDGET_EXHAUSTED"
    assert p["w|BTC|LONG"]["size"] == 1.0  # rien touché


def test_l3_not_stuck_not_touched():
    from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck

    p = {"w|BTC|LONG": {"size": 1.0, "avg_price": 100.0, "opened_at_ms": NOW_MS - 1_000, "coin": "BTC"}}
    env = {"HYPERSMART_V26_AUTO_UNSTUCK": "1"}
    # sous l'eau mais trop jeune ; et position gagnante jamais candidate
    assert apply_auto_unstuck(p, [], {"BTC": 98.0}, now_ms=NOW_MS, env=env) == []
    p2 = {"w|BTC|LONG": {"size": 1.0, "avg_price": 100.0, "opened_at_ms": NOW_MS - 4_000_000, "coin": "BTC"}}
    assert apply_auto_unstuck(p2, [], {"BTC": 105.0}, now_ms=NOW_MS, env=env) == []


# ================================================================ L4 halt gradué

def test_l4_escalade_amber_puis_red_puis_cooldown():
    from hl_observer.risk.graded_halt import AMBER, GREEN, RED, GradedHaltStateMachine

    sm = GradedHaltStateMachine()
    env = {"HYPERSMART_V26_GRADED_HALT": "1", "HYPERSMART_V26_HALT_AMBER_LOSS_USD": "10",
           "HYPERSMART_V26_HALT_RED_LOSS_USD": "20", "HYPERSMART_V26_HALT_COOLDOWN_MIN": "45"}
    ev_amber = [_close_event(pnl=-12.0, stop=False, at_ms=NOW_MS - 1_000)]
    assert sm.update(ev_amber, NOW_MS, env) == AMBER
    fx = sm.effects(env)
    assert fx.new_markets_blocked and fx.size_multiplier == 0.5 and not fx.entries_blocked_globally
    ev_red = ev_amber + [_close_event(pnl=-15.0, stop=False, at_ms=NOW_MS)]
    assert sm.update(ev_red, NOW_MS + 1_000, env) == RED
    fx2 = sm.effects(env)
    assert fx2.entries_blocked_globally and fx2.force_exit_all
    sm.mark_forced_exit_done()
    assert sm.effects(env).force_exit_all is False        # une seule fois par épisode
    # pertes hors fenêtre : cible GREEN mais descente UN palier après cooldown seulement
    later = NOW_MS + 300 * 60_000
    assert sm.update([], later, env) == AMBER              # RED -> AMBER (cooldown passé)
    assert sm.update([], later + 1_000, env) == AMBER      # pas de saut direct GREEN
    assert sm.update([], later + 46 * 60_000, env) == GREEN


def test_l4_force_exit_all_writes_paper_closes():
    from hl_observer.risk.graded_halt import force_exit_all_positions

    p = {"w|BTC|LONG": {"size": 2.0, "avg_price": 100.0, "coin": "BTC"}}
    ledger: list[dict] = []
    closed = force_exit_all_positions(p, ledger, {"BTC": 95.0}, now_ms=NOW_MS, cost_bps=0.0)
    assert len(closed) == 1 and p == {}
    assert ledger[0]["exit_method"] == "GRADED_HALT_RED_FORCE_EXIT"
    assert ledger[0]["estimated_net_pnl_usdc"] == pytest.approx(-10.0)  # 2 × (95-100)
    # pas de mark => pas de close inventé
    p2 = {"w|ETH|LONG": {"size": 1.0, "avg_price": 100.0, "coin": "ETH"}}
    assert force_exit_all_positions(p2, [], {}, now_ms=NOW_MS) == [] and "w|ETH|LONG" in p2


# ================================================================ L6 Kelly leader

def test_l6_neutral_under_min_trades_and_flag_off():
    from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK as book

    for _ in range(5):
        book.record_close("0xW", 1.0, 50.0)
    env_on = {"HYPERSMART_V26_KELLY_LEADER": "1"}
    assert book.multiplier("0xW", env_on) == 1.0          # < 10 trades => neutre
    assert book.multiplier("", env_on) == 1.0             # wallet inconnu => neutre
    assert book.multiplier("0xW", {}) == 1.0              # flag OFF => neutre


def test_l6_kelly_applied_and_bounded():
    from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK as book

    env = {"HYPERSMART_V26_KELLY_LEADER": "1"}
    for i in range(20):   # 70% WR, gains 4%, pertes 2% => edge net positif
        book.record_close("0xGOOD", 2.0 if i % 10 < 7 else -1.0, 50.0)
    s = book.stats("0xGOOD", env)
    assert s.sample_size == 20 and s.reason == "KELLY_APPLIED"
    assert 1.0 < s.multiplier <= 2.0
    for i in range(20):   # perdant systématique => réduit à 0.5
        book.record_close("0xBAD", -1.5, 50.0)
    sb = book.stats("0xBAD", env)
    assert sb.multiplier == 0.5 and sb.reason == "KELLY_NEGATIVE_REDUCED"


def test_l6_ingests_from_ledger_and_scales_scorer(monkeypatch):
    from hl_observer.copying.realtime_magic_score import (
        RealtimeCopyScoreInput,
        score_realtime_copy_candidate,
    )
    from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK as book

    events = [_close_event(pnl=-1.5, wallet="0xbad", notional=50.0, at_ms=NOW_MS - i) for i in range(15)]
    assert book.update_from_ledger_events(events) == 15
    monkeypatch.setenv("HYPERSMART_V26_KELLY_LEADER", "1")
    inp = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=60.0,
        leader_consistency_factor=1.0, signal_age_ms=500, consensus_wallets=3,
        liquidity_score=0.9, leader_score=90.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=40.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=10, coin="BTC", leader_wallet="0xbad",
    )
    s = score_realtime_copy_candidate(inp)
    assert any(w.startswith("KELLY_LEADER_MULT_0.50") for w in s.warnings)
    baseline = score_realtime_copy_candidate(RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=60.0,
        leader_consistency_factor=1.0, signal_age_ms=500, consensus_wallets=3,
        liquidity_score=0.9, leader_score=90.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=40.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=10, coin="BTC", leader_wallet="",
    ))
    assert s.simulated_notional_usdt == pytest.approx(baseline.simulated_notional_usdt * 0.5, rel=1e-6)


# ================================================================ L7 budget tier + WE/WEL

def test_l7_tiers_and_budgets():
    from hl_observer.edge.tier_cost_budget import budget_bps_for_tier, cost_budget_veto, tier_of

    assert tier_of(90) == "S" and tier_of(75) == "A" and tier_of(55) == "B" and tier_of(10) == "WATCH"
    assert budget_bps_for_tier("S") == 80.0 and budget_bps_for_tier("WATCH") == 20.0
    assert cost_budget_veto(leader_score=90, copy_degradation_bps=70) is None
    assert cost_budget_veto(leader_score=55, copy_degradation_bps=35) == "COST_BUDGET_EXCEEDED"
    assert cost_budget_veto(leader_score=None, copy_degradation_bps=35) is None  # inconnu ne bloque pas


def test_l7_wallet_exposure_and_wel():
    from hl_observer.edge.tier_cost_budget import check_add_allowed, wallet_exposure, wel_per_position

    assert wallet_exposure(3500.0, 1000.0) == 3.5           # exemple exact passivbot
    assert wel_per_position(2.0, 4) == 0.5
    ok = check_add_allowed(current_position_notional_usd=100.0, add_notional_usd=50.0,
                           unleveraged_balance_usd=1000.0, total_wallet_exposure_limit=2.0, n_positions=4)
    assert ok.allowed and ok.we == pytest.approx(0.15)
    ko = check_add_allowed(current_position_notional_usd=450.0, add_notional_usd=100.0,
                           unleveraged_balance_usd=1000.0, total_wallet_exposure_limit=2.0, n_positions=4)
    assert not ko.allowed and ko.reason == "PORTFOLIO_EXPOSURE_TOO_HIGH"


# ================================================================ L8 qualité marché

def test_l8_universe_topk_and_hysteresis():
    from hl_observer.signals.market_quality_score import DEFAULT_MARKET_QUALITY_BOOK as book

    env = {"HYPERSMART_V26_MQ_TOP_K": "2", "HYPERSMART_V26_MQ_HYSTERESIS_BUFFER": "1"}
    book.observe("BTC", range_bps=40, liquidity_score=0.9, env=env, now=1000.0)
    book.observe("ETH", range_bps=35, liquidity_score=0.8, env=env, now=1000.0)
    book.observe("DOGE", range_bps=2, liquidity_score=0.1, env=env, now=1000.0)   # mort + illiquide
    assert book.allowed("BTC", env) is True and book.allowed("ETH", env) is True
    assert book.allowed("DOGE", env) is False
    assert book.allowed("INCONNU", env) is None            # jamais noté => ne bloque pas


def test_l8_veto_via_entry_hook():
    from hl_observer.signals.market_quality_score import DEFAULT_MARKET_QUALITY_BOOK as book
    from hl_observer.signals.v26_entry_vetos import apply_v26_entry_vetos

    env = {"HYPERSMART_V26_MARKET_QUALITY": "1", "HYPERSMART_V26_MQ_TOP_K": "1",
           "HYPERSMART_V26_MQ_HYSTERESIS_BUFFER": "0"}
    book.observe("BTC", range_bps=40, liquidity_score=0.9, env=env, now=1000.0)
    book.observe("DOGE", range_bps=2, liquidity_score=0.05, env=env, now=1000.0)
    out = apply_v26_entry_vetos(coin="DOGE", side="LONG", edge_remaining_bps=50.0, env=env)
    assert "MARKET_QUALITY_LOW" in out
    out2 = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=50.0, env=env)
    assert "MARKET_QUALITY_LOW" not in out2


# ================================================================ hook composé (L4+L5+L7)

def test_hook_composes_l4_l5_l7():
    from hl_observer.risk.graded_halt import DEFAULT_GRADED_HALT
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK
    from hl_observer.signals.v26_entry_vetos import apply_v26_entry_vetos

    env = {"HYPERSMART_V26_GRADED_HALT": "1", "HYPERSMART_V26_PROTECTIONS": "1",
           "HYPERSMART_V26_TIER_COST_BUDGET": "1", "HYPERSMART_V26_SG_TRADE_LIMIT": "2"}
    DEFAULT_PROTECTIONS_BOOK.update_from_ledger_events(
        [_close_event(pnl=-2.0, at_ms=NOW_MS - 10_000), _close_event(pnl=-2.0, at_ms=NOW_MS - 5_000)]
    )
    DEFAULT_GRADED_HALT.update([_close_event(pnl=-30.0, stop=False, at_ms=NOW_MS)], NOW_MS, env)
    out = apply_v26_entry_vetos(
        coin="BTC", side="LONG", edge_remaining_bps=50.0, env=env, now_ms=NOW_MS,
        leader_score=10.0, copy_degradation_bps=25.0,
    )
    assert "GRADED_HALT_RED" in out
    assert "STOPLOSS_GUARD_ACTIVE" in out
    assert "COST_BUDGET_EXCEEDED" in out                    # WATCH budget 20 < 25
    # tout OFF => rien (comportement V25)
    assert apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=50.0,
                                 env={}, now_ms=NOW_MS, leader_score=10.0,
                                 copy_degradation_bps=25.0) == []


# ================================================================ reliquat coûts carnet

def test_book_costs_walkthebook_and_freshness():
    from hl_observer.collection import l2_snapshot_cache as l2c

    bids = [(99.9, 10.0)]
    asks = [(100.1, 0.2), (100.5, 5.0)]   # 20$ au best, il faut walker le 2e niveau pour 50$
    costs = l2c.compute_book_costs(bids, asks, 50.0)
    assert costs is not None
    spread, slip = costs
    assert spread == pytest.approx(20.0, rel=0.01)          # (100.1-99.9)/100 en bps
    assert slip > 5.0                                        # walk => prix moyen > best ask
    assert l2c.compute_book_costs([], asks, 50.0) is None
    env = {"HYPERSMART_V26_LIVE_BOOK_COSTS": "1"}
    l2c.push_costs("BTC", spread, slip, ts=1000.0)
    assert l2c.live_costs_for("BTC", env, now=1050.0) == (spread, slip)
    assert l2c.live_costs_for("BTC", env, now=5000.0) is None   # périmé => None
    assert l2c.live_costs_for("BTC", {}, now=1050.0) is None    # flag OFF => None


def test_scorer_uses_live_costs_when_flag_on(monkeypatch):
    from hl_observer.collection import l2_snapshot_cache as l2c
    from hl_observer.copying.realtime_magic_score import (
        RealtimeCopyScoreInput,
        score_realtime_copy_candidate,
    )

    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    l2c.push_costs("BTC", 25.0, 30.0)                        # spread>20 ET slip>25
    inp = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=200.0,
        leader_consistency_factor=1.0, signal_age_ms=500, consensus_wallets=3,
        liquidity_score=0.9, leader_score=90.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=40.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=10, coin="BTC",
    )
    s = score_realtime_copy_candidate(inp)
    assert "LIVE_BOOK_COSTS_USED" in s.warnings
    assert "SPREAD_TOO_WIDE" in s.refusal_reasons and "SLIPPAGE_TOO_HIGH" in s.refusal_reasons


def test_l2book_parse():
    from hl_observer.collection.l2_snapshot_cache import parse_l2book

    payload = {"levels": [[{"px": "99.9", "sz": "1"}], [{"px": "100.1", "sz": "2"}]]}
    parsed = parse_l2book(payload)
    assert parsed == ([(99.9, 1.0)], [(100.1, 2.0)])
    assert parse_l2book({"nope": 1}) is None


# ================================================================ pipeline d'exits

def test_exit_pipeline_ingests_and_unstucks_via_wrapper(monkeypatch):
    from hl_observer.paper_trading.sl_tp import SLTPConfig
    from hl_observer.paper_trading.vol_adjusted_barriers import apply_sltp_exits_vol_adjusted
    from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK

    monkeypatch.setenv("HYPERSMART_V26_AUTO_UNSTUCK", "1")
    monkeypatch.delenv("HYPERSMART_V26_RECORD_CANDIDATES", raising=False)
    cfg = SLTPConfig(stop_loss_bps=400.0, take_profit_bps=800.0)
    positions = {
        "w|BTC|LONG": {
            "size": 1.0,
            "avg_price": 100.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "opened_at_ms": NOW_MS - 100_000,
            "coin": "BTC",
        },
        "w|ETH|LONG": {
            "size": 1.0,
            "avg_price": 100.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "opened_at_ms": NOW_MS - 4_000_000,
            "coin": "ETH",
        },
    }
    ledger: list[dict] = []
    # BTC -500bps => SL(400) le stoppe ; ETH -200bps vieux => pas stoppé, candidat unstuck
    marks = {"BTC": 95.0, "ETH": 98.0}
    closed = apply_sltp_exits_vol_adjusted(
        positions, ledger, marks, cost_bps=0.0, now_ms=NOW_MS, config=cfg, env=None,
    )
    assert any(c.get("reason") == "STOP_LOSS" for c in closed)          # BTC stoppé
    assert any(e.get("exit_method") == "UNSTUCK_PARTIAL" for e in ledger)  # ETH unstuck partiel
    assert positions["w|ETH|LONG"]["size"] == pytest.approx(0.9)
    assert DEFAULT_PROTECTIONS_BOOK.status()["closes_tracked"] >= 1     # book nourri du ledger


# ================================================================ L9 A/B replay

def _mk_candidate(ts, coin="BTC", side="LONG", edge=30.0, mid=100.0, score=90.0, degr=12.0):
    return {"recorded_at": ts, "coin": coin, "direction": side, "edge_remaining_bps": edge,
            "current_mid": mid, "leader_score": score, "copy_degradation_bps": degr,
            "liquidity_score": 0.9, "leader_notional_usdt": 50.0}


def test_l9_ab_replay_arms_differ_and_metrics_correct():
    from hl_observer.backtesting.ab_flag_replay import run_ab_replay

    # 6 candidats BTC à edge décroissant (30→12) : le bras B (trend veto) refuse les derniers
    cands = [_mk_candidate(1000.0 + i * 60, edge=e) for i, e in enumerate((30, 28, 26, 18, 15, 12))]
    # chemin de marks réel : monte doucement => trades gagnants au timeout
    marks = [{"ts": 900.0 + i * 30, "coin": "BTC", "mid": 100.0 + i * 0.01} for i in range(200)]
    report = run_ab_replay(cands, marks, arm_b_env={"HYPERSMART_V26_VOL_BARRIERS": "0"},
                           horizon_min=30.0, cost_bps=0.0)
    a, b = report["arm_a"], report["arm_b"]
    assert a["candidates_seen"] == b["candidates_seen"] == 6
    assert a["trades"] == 6                     # baseline accepte tout
    assert b["trades"] < a["trades"]            # B a refusé au moins les edges décroissants
    assert report["context"] == "REPLAY"
    assert isinstance(report["delta_net_usd"], float)


def test_l9_unmeasurable_excluded_from_both_arms():
    from hl_observer.backtesting.ab_flag_replay import run_ab_replay

    cands = [_mk_candidate(1000.0)]
    report = run_ab_replay(cands, [], horizon_min=30.0)      # aucun mark futur
    assert report["arm_a"]["trades"] == 0 and report["arm_b"]["trades"] == 0
    assert report["arm_a"]["unmeasurable_excluded"] == 1


def test_l9_profit_factor_math():
    from hl_observer.backtesting.ab_flag_replay import ArmMetrics

    m = ArmMetrics("t")
    m.trades = [10.0, -5.0, 6.0, -3.0]
    r = m.report()
    assert r["profit_factor"] == pytest.approx(16.0 / 8.0)
    assert r["net_total_usd"] == pytest.approx(8.0)
    assert r["max_drawdown_usd"] == pytest.approx(5.0)


# ================================================================ sécurité

def test_no_real_trade_surface_in_new_modules():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "hl_observer"
    pure_modules = (
        "risk/protections_v26.py", "paper_trading/auto_unstuck.py", "risk/graded_halt.py",
        "risk/kelly_leader_book.py", "edge/tier_cost_budget.py", "signals/market_quality_score.py",
        "paper_trading/v26_exit_pipeline.py", "backtesting/ab_flag_replay.py",
    )
    for rel in pure_modules:
        text = (root / rel).read_text(encoding="utf-8")
        for forbidden in ("requests", "httpx", "aiohttp", "websocket", "/exchange", "private_key", "sign("):
            assert forbidden not in text, f"{rel}: {forbidden}"
    # le cache carnet a un poller réseau PUBLIC opt-in, mais jamais de surface d'exécution
    l2 = (root / "collection/l2_snapshot_cache.py").read_text(encoding="utf-8")
    for forbidden in ("/exchange", "private_key", "sign(", "wallet_connect"):
        assert forbidden not in l2
