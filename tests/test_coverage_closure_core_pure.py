from __future__ import annotations

import math
import time

import pytest

from hl_observer.analysis.copy_delay_model import copy_delay_decay
from hl_observer.analysis.entry_edge import entry_edge_score
from hl_observer.analysis.exit_edge import exit_quality_score
from hl_observer.copy_mode.copy_session_controller import (
    CopySession,
    CopySessionState,
    pause_copy_session,
    start_copy_session,
    stop_copy_session,
)
from hl_observer.copy_mode.wallet_subscription_planner import plan_wallet_subscriptions
from hl_observer.copying.circuit_breaker import (
    CircuitBreakerConfig as CopyCircuitConfig,
    CircuitBreakerState,
    CircuitState,
    evaluate_circuit_breaker,
    record_trade_result,
    reset_circuit_breaker,
)
from hl_observer.copying.kelly_sizing import KellySizingConfig, kelly_criterion_size
from hl_observer.copying.leader_pnl_tracker import LeaderPerformance, LeaderPnLTracker, LeaderTradeRecord
from hl_observer.market_data.exchange_fee_normalizer import normalize_fee_bps
from hl_observer.risk.advanced_risk_manager import (
    AdvancedRiskConfig,
    AdvancedRiskManager,
    RiskVeto,
    VolatilityRegime,
    VolatilityState,
)
from hl_observer.simulation.freshness_gates import (
    categorize_signal_by_freshness,
    evaluate_signal_freshness,
    validate_signal_for_live,
)
from hl_observer.simulation.modes import (
    MAX_HARD_SIGNAL_AGE_MS,
    MAX_LIVE_SIGNAL_AGE_MS,
    SignalSource,
    SimulationMode,
    is_test_fixture_wallet,
)
from hl_observer.universe.coin_universe import build_coin_universe


def test_analysis_edge_helpers_cover_bounds_and_invalid_inputs() -> None:
    assert entry_edge_score(expectancy=None) == 0.0
    assert entry_edge_score(expectancy=150.0) == 100.0
    assert entry_edge_score(expectancy=5.0, copy_delay_bps=10.0) == 0.0
    assert entry_edge_score(expectancy=35.0, copy_delay_bps=5.0) == 30.0

    assert exit_quality_score(average_win=None, average_loss=None) == 0.0
    assert exit_quality_score(average_win=5.0, average_loss=None) == 50.0
    assert exit_quality_score(average_win=5.0, average_loss=0.0) == 50.0
    assert exit_quality_score(average_win=10.0, average_loss=5.0) == 100.0
    assert exit_quality_score(average_win=-1.0, average_loss=5.0) == 0.0

    assert copy_delay_decay(10.0, delay_ms=100, half_life_ms=0) == 0.0
    assert copy_delay_decay(10.0, delay_ms=0, half_life_ms=100) == pytest.approx(10.0)
    assert copy_delay_decay(10.0, delay_ms=100, half_life_ms=100) == pytest.approx(10.0 / math.e)


def test_modes_and_fixture_wallet_contracts() -> None:
    assert SimulationMode.is_live("LIVE")
    assert SimulationMode.is_backtest("backtest")
    assert SimulationMode.is_replay(SimulationMode.REPLAY)
    assert SimulationMode.is_test_fixture("TEST_FIXTURE")
    assert not SimulationMode.is_live(None)

    assert SignalSource.is_live_eligible(SignalSource.FRESH)
    assert not SignalSource.is_live_eligible(SignalSource.TEST)
    assert SignalSource.is_replay(SignalSource.REPLAY_JSONL)
    assert SignalSource.is_replay(SignalSource.BACKTEST_DB)
    assert not SignalSource.is_replay(SignalSource.FRESH)

    assert not is_test_fixture_wallet(None)
    assert is_test_fixture_wallet("0x1111111111111111111111111111111111111111")
    assert is_test_fixture_wallet("0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert not is_test_fixture_wallet("0x123")


def test_freshness_gate_all_modes_and_boundaries() -> None:
    fixture = "0x1111111111111111111111111111111111111111"
    normal = "0x123"

    row = evaluate_signal_freshness(1, fixture, SimulationMode.LIVE)
    assert not row.passed and row.mode_eligible == SimulationMode.TEST_FIXTURE

    row = evaluate_signal_freshness(MAX_LIVE_SIGNAL_AGE_MS, normal, SimulationMode.LIVE)
    assert row.passed and row.mode_eligible == SimulationMode.LIVE

    row = evaluate_signal_freshness(MAX_LIVE_SIGNAL_AGE_MS + 1, normal, SimulationMode.LIVE)
    assert not row.passed and row.mode_eligible == SimulationMode.BACKTEST

    row = evaluate_signal_freshness(MAX_HARD_SIGNAL_AGE_MS + 1, normal, SimulationMode.LIVE)
    assert not row.passed and row.mode_eligible is None

    row = evaluate_signal_freshness(MAX_HARD_SIGNAL_AGE_MS, normal, SimulationMode.BACKTEST)
    assert row.passed and row.mode_eligible == SimulationMode.BACKTEST

    row = evaluate_signal_freshness(MAX_HARD_SIGNAL_AGE_MS + 1, normal, SimulationMode.BACKTEST)
    assert not row.passed and row.mode_eligible is None

    row = evaluate_signal_freshness(999_999, normal, SimulationMode.REPLAY)
    assert row.passed and row.mode_eligible == SimulationMode.REPLAY

    assert validate_signal_for_live(1, normal, SignalSource.TEST)[0] is False
    assert validate_signal_for_live(MAX_LIVE_SIGNAL_AGE_MS + 1, normal, SignalSource.FRESH)[0] is False
    assert validate_signal_for_live(1, fixture, SignalSource.FRESH)[0] is False
    assert validate_signal_for_live(1, normal, SignalSource.FRESH) == (True, "")

    assert categorize_signal_by_freshness(1000) == "ULTRA_FRESH"
    assert categorize_signal_by_freshness(1001) == "FRESH"
    assert categorize_signal_by_freshness(5000) == "WARM"
    assert categorize_signal_by_freshness(20_000) == "STALE"
    assert categorize_signal_by_freshness(30_001) == "VERY_STALE"


def test_coin_universe_rejections_and_limit() -> None:
    result = build_coin_universe(
        [" btc ", "ETH", "BTC", "SOL", "DOGE", ""],
        whitelist=["BTC", "ETH", "SOL", "DOGE"],
        blacklist=["SOL"],
        max_coins=2,
    )
    assert result.selected == ("BTC", "ETH")
    reasons = [row["reason"] for row in result.rejected]
    assert "DUPLICATE_COIN" in reasons
    assert "BLACKLISTED_COIN" in reasons
    assert "COIN_UNIVERSE_LIMIT" in reasons

    result = build_coin_universe(["BTC", "ETH"], whitelist=["BTC"])
    assert result.selected == ("BTC",)
    assert result.rejected == ({"coin": "ETH", "reason": "NOT_IN_WHITELIST"},)


def test_wallet_subscription_ranking_duplicates_and_limits() -> None:
    result = plan_wallet_subscriptions(
        [" 0xB ", "0xa", "0xB", "", "0xc"],
        scores={"0xa": 10, "0xb": 5, "0xc": 1},
        max_unique_users=2,
    )
    assert result.selected_wallets == ("0xa", "0xb")
    assert result.safe_for_ws
    reasons = [row["reason"] for row in result.rejected_wallets]
    assert "DUPLICATE_WALLET" in reasons
    assert "WS_UNIQUE_USER_LIMIT" in reasons

    zero = plan_wallet_subscriptions(["0xa"], max_unique_users=-1)
    assert zero.selected_wallets == ()
    assert zero.safe_for_ws is False


def test_copy_session_state_transitions_are_local_and_paper_only() -> None:
    session = CopySession("s")
    assert session.state == CopySessionState.STOPPED
    assert session.paper_only and not session.external_action

    running = start_copy_session(session, now_ms=10)
    assert running.state == CopySessionState.RUNNING
    assert running.started_at_ms == 10 and running.stopped_at_ms is None

    paused = pause_copy_session(running)
    assert paused.state == CopySessionState.PAUSED and paused.reason == "LOCAL_PAUSE"

    stopped = stop_copy_session(paused, now_ms=20, reason="TEST_STOP")
    assert stopped.state == CopySessionState.STOPPED
    assert stopped.stopped_at_ms == 20 and stopped.reason == "TEST_STOP"


def test_exchange_fee_normalizer_all_units() -> None:
    fraction = normalize_fee_bps("x", maker=0.0002, taker=0.0005)
    assert fraction.maker_bps == 2.0 and fraction.taker_bps == 5.0
    percent = normalize_fee_bps("x", maker=0.02, taker=0.05, input_unit="percent")
    assert percent.maker_bps == 2.0 and percent.taker_bps == 5.0
    bps = normalize_fee_bps("x", maker=2, taker=5, input_unit="bps")
    assert bps.maker_bps == 2.0 and bps.taker_bps == 5.0


def test_volatility_state_trims_and_advanced_var_basics() -> None:
    state = VolatilityState(max_window=3)
    for value in (1.0, 2.0, 3.0, 4.0):
        state.add_return(value)
    assert state.recent_returns == [2.0, 3.0, 4.0]

    manager = AdvancedRiskManager()
    manager.initialize(1000.0)
    assert manager.compute_var_95([]) == 0.0
    manager.vol_state.annualized_vol_pct = 50.0
    assert manager.compute_var_95([100.0]) > 0.0


def test_advanced_risk_daily_loss_drawdown_total_category_and_var_vetoes() -> None:
    manager = AdvancedRiskManager()
    manager.initialize(1000.0)
    manager.daily_state.day_realized_pnl_usdt = -250.0
    row = manager.evaluate_risk(coin="BTC", proposed_notional_usdt=10.0)
    assert not row.allowed and row.veto == RiskVeto.DAILY_LOSS_HALT

    manager = AdvancedRiskManager()
    manager.initialize(1000.0)
    manager.update_equity(400.0)
    row = manager.evaluate_risk(coin="BTC", proposed_notional_usdt=10.0)
    assert not row.allowed and row.veto == RiskVeto.MAX_DRAWDOWN_HALT

    manager = AdvancedRiskManager()
    manager.initialize(1000.0)
    row = manager.evaluate_risk(
        coin="BTC",
        proposed_notional_usdt=100.0,
        current_open_notionals=[950.0],
    )
    assert not row.allowed and row.veto == RiskVeto.TOTAL_EXPOSURE_EXCEEDED

    manager = AdvancedRiskManager(config=AdvancedRiskConfig(max_per_category_pct=5.0))
    manager.initialize(1000.0)
    row = manager.evaluate_risk(coin="BTC", proposed_notional_usdt=100.0)
    assert not row.allowed and row.veto == RiskVeto.CATEGORY_EXPOSURE_EXCEEDED

    manager = AdvancedRiskManager(config=AdvancedRiskConfig(max_var_pct=0.001))
    manager.initialize(1000.0)
    manager.vol_state.annualized_vol_pct = 100.0
    row = manager.evaluate_risk(coin="BTC", proposed_notional_usdt=100.0)
    assert not row.allowed and row.veto == RiskVeto.VAR_LIMIT_EXCEEDED


def test_advanced_risk_sizing_alpha_correlation_lifecycle_and_cleanup() -> None:
    manager = AdvancedRiskManager()
    manager.initialize(1000.0)

    manager.vol_state.current_regime = VolatilityRegime.EXTREME
    extreme = manager.evaluate_risk(coin="ETH", proposed_notional_usdt=10.0)
    assert extreme.allowed and extreme.sizing_multiplier == manager.config.vol_extreme_sizing_mult
    assert "extreme_vol_sizing" in extreme.reasons

    manager.vol_state.current_regime = VolatilityRegime.HIGH
    high = manager.evaluate_risk(coin="ETH", proposed_notional_usdt=10.0)
    assert high.allowed and high.sizing_multiplier == manager.config.vol_high_sizing_mult

    first = manager.evaluate_risk(coin="ETH", proposed_notional_usdt=10.0, signal_id="old")
    assert first.allowed and "old" in manager.signal_first_seen
    manager.signal_first_seen["old"] -= (manager.config.alpha_decay_max_hours + 1.0) * 3600.0
    old = manager.evaluate_risk(coin="ETH", proposed_notional_usdt=10.0, signal_id="old")
    assert not old.allowed and old.veto == RiskVeto.ALPHA_DECAYED

    manager.open_positions_coins = ["BTC", "BTC"]
    correlated = manager.evaluate_risk(coin="btc", proposed_notional_usdt=10.0)
    assert correlated.allowed and correlated.sizing_multiplier == 0.5
    assert "correlated_positions" in correlated.reasons

    manager.on_position_opened("SOL", 25.0, "alt")
    assert "SOL" in manager.open_positions_coins and manager.category_exposures["alt"] == 25.0
    before = manager.current_equity_usdt
    manager.on_position_closed("SOL", 25.0, 3.0, "alt")
    assert manager.category_exposures["alt"] == 0.0
    assert manager.current_equity_usdt == before + 3.0
    assert manager.daily_state.trades_today == 1

    manager.signal_first_seen["stale"] = time.time() - 100 * 3600
    removed = manager.cleanup_old_signals(max_age_hours=24)
    assert removed >= 1 and "stale" not in manager.signal_first_seen
    report = manager.get_risk_report()
    assert report["simulation_only"] is True and report["real_orders_created"] == 0


def test_advanced_risk_recomputes_low_normal_high_extreme() -> None:
    manager = AdvancedRiskManager()
    manager.initialize(1000.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    assert manager.vol_state.current_regime == VolatilityRegime.LOW

    manager.vol_state.recent_returns = [0.001, -0.001, 0.001, -0.001, 0.001]
    manager._recompute_vol_regime()
    assert manager.vol_state.last_computed_at > 0
    assert manager.vol_state.annualized_vol_pct >= 0


def _trade(addr: str, pnl: float, index: int) -> LeaderTradeRecord:
    return LeaderTradeRecord(
        leader_address=addr,
        coin="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        notional_usdt=10.0,
        pnl_usdt=pnl,
        pnl_bps=pnl * 10,
        entry_timestamp=float(index),
        exit_timestamp=float(index + 1),
        hold_duration_ms=1000,
        signal_age_at_entry_ms=50,
    )


def test_leader_performance_properties_and_statuses() -> None:
    perf = LeaderPerformance("a")
    assert perf.win_rate == 0.0
    assert perf.avg_pnl_per_trade_usdt == 0.0
    assert perf.avg_pnl_per_trade_bps == 0.0
    assert perf.profit_factor == 0.0
    assert perf.status == "EVALUATING"

    perf.total_trades = 3
    perf.winning_trades = 2
    perf.total_pnl_usdt = 5.0
    assert perf.status == "PROFITABLE"
    assert math.isinf(perf.profit_factor)

    perf.total_pnl_usdt = -5.0
    perf.winning_trades = 0
    perf.consecutive_losses = 4
    perf.max_single_loss_usdt = -2.0
    assert perf.status == "EJECT_STREAK"
    assert perf.profit_factor == 0.0

    perf.consecutive_losses = 0
    perf.total_trades = 5
    assert perf.status == "EJECT_NEGATIVE_PNL"

    perf.total_pnl_usdt = 1.0
    perf.winning_trades = 1
    assert perf.status == "EJECT_LOW_WIN_RATE"

    perf.winning_trades = 2
    perf.total_pnl_usdt = 0.0
    assert perf.status == "MARGINAL"


def test_leader_tracker_rotation_summary_and_ejection_paths() -> None:
    tracker = LeaderPnLTracker()
    assert tracker.get_leader_performance("missing") is None
    assert tracker.should_eject_leader("missing") == (False, "no_data")

    tracker.record_trade(_trade("A", 2.0, 0))
    assert tracker.should_eject_leader("A") == (False, "evaluating")
    tracker.record_trade(_trade("A", 2.0, 1))
    tracker.record_trade(_trade("A", 2.0, 2))
    assert tracker.get_leader_performance("a").status == "PROFITABLE"
    assert tracker.get_profitable_leaders() == ["a"]

    for i in range(5):
        tracker.record_trade(_trade("B", -1.0, i))
    eject, reason = tracker.should_eject_leader("b")
    assert eject and ("consecutive_losses" in reason or "negative_pnl" in reason)
    assert any(addr == "b" for addr, _ in tracker.get_leaders_to_eject())

    perfs = tracker.get_all_performances()
    assert perfs[0].leader_address == "a"
    summary = tracker.get_session_summary()
    assert summary["total_leaders_tracked"] == 2
    assert summary["total_trades"] == 8
    assert summary["best_leader"] == "a"
    assert summary["worst_leader"] == "b"
    assert summary["leaders_to_eject"] >= 1


def test_kelly_sizing_rejects_low_probability_negative_edge_and_full_exposure() -> None:
    low = kelly_criterion_size(
        edge_remaining_bps=1.0,
        leader_score=10.0,
        consensus_wallets=1,
    )
    assert low.position_size_usdt == 0.0 and low.edge_quality == "REJECT"
    assert "WIN_PROBABILITY_TOO_LOW" in low.warnings

    negative = kelly_criterion_size(
        edge_remaining_bps=1.0,
        leader_score=100.0,
        consensus_wallets=1,
        win_rate_estimate=0.45,
        config=KellySizingConfig(min_win_probability=0.0),
    )
    assert negative.position_size_usdt == 0.0
    assert "KELLY_NEGATIVE_NO_EDGE" in negative.warnings

    capped = kelly_criterion_size(
        edge_remaining_bps=50.0,
        leader_score=100.0,
        consensus_wallets=4,
        win_rate_estimate=0.7,
        current_open_exposure_usdt=200.0,
    )
    assert capped.position_size_usdt == 0.0
    assert "MAX_TOTAL_EXPOSURE_CAP_ACTIVE" in capped.warnings


def test_kelly_sizing_caps_remaining_leader_confidence_and_quality() -> None:
    high = kelly_criterion_size(
        edge_remaining_bps=50.0,
        leader_score=100.0,
        consensus_wallets=4,
        win_rate_estimate=0.7,
        leader_notional_usdt=12.0,
    )
    assert high.position_size_usdt <= 12.0
    assert high.edge_quality == "HIGH"

    medium = kelly_criterion_size(
        edge_remaining_bps=15.0,
        leader_score=100.0,
        consensus_wallets=4,
        win_rate_estimate=0.6,
    )
    assert medium.edge_quality in {"MEDIUM", "HIGH"}

    low = kelly_criterion_size(
        edge_remaining_bps=8.0,
        leader_score=100.0,
        consensus_wallets=4,
        win_rate_estimate=0.55,
    )
    assert low.edge_quality == "LOW"

    partial = kelly_criterion_size(
        edge_remaining_bps=50.0,
        leader_score=100.0,
        consensus_wallets=4,
        win_rate_estimate=0.7,
        current_open_exposure_usdt=197.0,
    )
    assert partial.position_size_usdt == 0.0
    assert "POSITION_SIZE_BELOW_MINIMUM" in partial.warnings

    confidence = kelly_criterion_size(
        edge_remaining_bps=50.0,
        leader_score=30.0,
        consensus_wallets=4,
        win_rate_estimate=0.72,
        config=KellySizingConfig(min_win_probability=0.45),
    )
    assert "LOW_CONFIDENCE_SCALING" in confidence.warnings


def test_copy_circuit_breaker_pause_halt_rate_recovery_and_recording() -> None:
    now = time.time()

    paused = CircuitBreakerState(state=CircuitState.PAUSED, paused_at=now)
    paused = evaluate_circuit_breaker(paused, CopyCircuitConfig(cooldown_minutes=30.0))
    assert paused.state == CircuitState.PAUSED and paused.sizing_multiplier == 0.0

    expired = CircuitBreakerState(state=CircuitState.PAUSED, paused_at=now - 3600)
    expired = evaluate_circuit_breaker(expired, CopyCircuitConfig(cooldown_minutes=1.0))
    assert expired.state == CircuitState.RECOVERY

    halted = CircuitBreakerState(state=CircuitState.HALTED)
    halted = evaluate_circuit_breaker(halted)
    assert halted.sizing_multiplier == 0.0 and "HALTED_MANUAL_RESET_REQUIRED" in halted.reasons

    dd_halt = CircuitBreakerState(peak_equity_usdt=1000, current_equity_usdt=800)
    assert evaluate_circuit_breaker(dd_halt).state == CircuitState.HALTED

    dd_pause = CircuitBreakerState(peak_equity_usdt=1000, current_equity_usdt=940)
    assert evaluate_circuit_breaker(dd_pause).state == CircuitState.PAUSED

    streak_halt = CircuitBreakerState(consecutive_losses=7)
    assert evaluate_circuit_breaker(streak_halt).state == CircuitState.HALTED

    streak_pause = CircuitBreakerState(consecutive_losses=4)
    assert evaluate_circuit_breaker(streak_pause).state == CircuitState.PAUSED

    rapid = CircuitBreakerState(recent_pnl_events=[(now, -60.0)])
    assert evaluate_circuit_breaker(rapid).state == CircuitState.PAUSED

    hourly = CircuitBreakerState(trades_this_hour=10)
    hourly = evaluate_circuit_breaker(hourly)
    assert hourly.sizing_multiplier == 0.0 and "RATE_LIMIT_HOURLY" in hourly.reasons

    daily = CircuitBreakerState(trades_this_day=50)
    daily = evaluate_circuit_breaker(daily)
    assert daily.sizing_multiplier == 0.0 and "RATE_LIMIT_DAILY" in daily.reasons

    recovery = CircuitBreakerState(state=CircuitState.RECOVERY, consecutive_wins_in_recovery=3)
    recovery = evaluate_circuit_breaker(recovery)
    assert recovery.state == CircuitState.NORMAL and recovery.sizing_multiplier == 1.0

    recovery = CircuitBreakerState(state=CircuitState.RECOVERY, consecutive_wins_in_recovery=1)
    recovery = evaluate_circuit_breaker(recovery)
    assert recovery.sizing_multiplier == pytest.approx(0.5)

    caution = CircuitBreakerState(peak_equity_usdt=1000, current_equity_usdt=965)
    caution = evaluate_circuit_breaker(caution)
    assert caution.state == CircuitState.CAUTION and caution.sizing_multiplier == pytest.approx(0.7)

    normal = CircuitBreakerState()
    normal = record_trade_result(normal, pnl_bps=-5.0, pnl_usdt=-1.0)
    assert normal.consecutive_losses == 1 and normal.trades_this_hour == 1
    normal.state = CircuitState.RECOVERY
    normal = record_trade_result(normal, pnl_bps=5.0, pnl_usdt=2.0)
    assert normal.consecutive_losses == 0 and normal.consecutive_wins_in_recovery == 1
    normal = reset_circuit_breaker(normal)
    assert normal.state == CircuitState.RECOVERY and normal.sizing_multiplier == 0.5
