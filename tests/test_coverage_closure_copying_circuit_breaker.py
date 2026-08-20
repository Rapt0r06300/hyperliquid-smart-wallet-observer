from __future__ import annotations

import pytest

import hl_observer.copying.circuit_breaker as cbm
from hl_observer.copying.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitState,
    evaluate_circuit_breaker,
    record_trade_result,
    reset_circuit_breaker,
)


def test_pause_cooldown_halt_and_manual_reset(monkeypatch) -> None:
    monkeypatch.setattr(cbm.time, "time", lambda: 1_000.0)
    cfg = CircuitBreakerConfig(cooldown_minutes=10.0)

    paused = CircuitBreakerState(state=CircuitState.PAUSED, paused_at=700.0)
    result = evaluate_circuit_breaker(paused, cfg)
    assert result.state is CircuitState.PAUSED
    assert result.sizing_multiplier == 0.0
    assert result.reasons[0].startswith("PAUSED_REMAINING_")

    paused.paused_at = 0.0
    result = evaluate_circuit_breaker(paused, cfg)
    assert result.state is CircuitState.RECOVERY
    assert "COOLDOWN_EXPIRED_ENTERING_RECOVERY" in result.reasons

    halted = CircuitBreakerState(state=CircuitState.HALTED)
    result = evaluate_circuit_breaker(halted, cfg)
    assert result.sizing_multiplier == 0.0
    assert result.reasons == ["HALTED_MANUAL_RESET_REQUIRED"]

    reset = reset_circuit_breaker(halted)
    assert reset.state is CircuitState.RECOVERY
    assert reset.sizing_multiplier == 0.5
    assert reset.reasons == ["MANUAL_RESET_ENTERING_RECOVERY"]


def test_drawdown_and_losing_streak_halt_pause_and_caution(monkeypatch) -> None:
    monkeypatch.setattr(cbm.time, "time", lambda: 2_000.0)
    cfg = CircuitBreakerConfig()

    halt_dd = CircuitBreakerState(peak_equity_usdt=1000.0, current_equity_usdt=890.0)
    assert evaluate_circuit_breaker(halt_dd, cfg).state is CircuitState.HALTED
    assert halt_dd.reasons[0].startswith("HALT_DRAWDOWN_")

    halt_streak = CircuitBreakerState(consecutive_losses=cfg.halt_losing_streak)
    assert evaluate_circuit_breaker(halt_streak, cfg).state is CircuitState.HALTED
    assert halt_streak.reasons[0].startswith("HALT_LOSING_STREAK_")

    pause_dd = CircuitBreakerState(peak_equity_usdt=1000.0, current_equity_usdt=940.0)
    assert evaluate_circuit_breaker(pause_dd, cfg).state is CircuitState.PAUSED
    assert pause_dd.paused_at == 2_000.0

    pause_streak = CircuitBreakerState(consecutive_losses=cfg.pause_losing_streak)
    assert evaluate_circuit_breaker(pause_streak, cfg).state is CircuitState.PAUSED
    assert pause_streak.reasons[0].startswith("PAUSE_LOSING_STREAK_")

    caution_dd = CircuitBreakerState(peak_equity_usdt=1000.0, current_equity_usdt=965.0)
    result = evaluate_circuit_breaker(caution_dd, cfg)
    assert result.state is CircuitState.CAUTION
    assert result.sizing_multiplier == pytest.approx(0.7)
    assert any(reason.startswith("CAUTION_DRAWDOWN_") for reason in result.reasons)

    caution_streak = CircuitBreakerState(consecutive_losses=cfg.caution_losing_streak)
    result = evaluate_circuit_breaker(caution_streak, cfg)
    assert result.state is CircuitState.CAUTION
    assert any(reason.startswith("CAUTION_STREAK_") for reason in result.reasons)


def test_rapid_loss_and_rate_limits(monkeypatch) -> None:
    monkeypatch.setattr(cbm.time, "time", lambda: 10_000.0)
    cfg = CircuitBreakerConfig(rapid_loss_bps=50.0, rapid_loss_window_minutes=15.0)

    rapid = CircuitBreakerState(
        recent_pnl_events=[(9_500.0, -30.0), (9_700.0, -25.0), (1.0, -999.0), (9_900.0, 50.0)]
    )
    result = evaluate_circuit_breaker(rapid, cfg)
    assert result.state is CircuitState.PAUSED
    assert any(reason.startswith("PAUSE_RAPID_LOSS_55bps") for reason in result.reasons)

    hourly = CircuitBreakerState(trades_this_hour=cfg.max_trades_per_hour)
    result = evaluate_circuit_breaker(hourly, cfg)
    assert result.sizing_multiplier == 0.0
    assert result.reasons == ["RATE_LIMIT_HOURLY"]

    daily = CircuitBreakerState(trades_this_day=cfg.max_trades_per_day)
    result = evaluate_circuit_breaker(daily, cfg)
    assert result.sizing_multiplier == 0.0
    assert result.reasons == ["RATE_LIMIT_DAILY"]


def test_recovery_normal_and_peak_refresh(monkeypatch) -> None:
    monkeypatch.setattr(cbm.time, "time", lambda: 5_000.0)
    cfg = CircuitBreakerConfig(recovery_trades_before_normal=3, recovery_sizing_multiplier=0.4)

    recovering = CircuitBreakerState(state=CircuitState.RECOVERY, consecutive_wins_in_recovery=1)
    result = evaluate_circuit_breaker(recovering, cfg)
    assert result.state is CircuitState.RECOVERY
    assert result.sizing_multiplier == pytest.approx(0.4)
    assert result.reasons == ["RECOVERY_MODE_SIZING_40%"]

    recovered = CircuitBreakerState(state=CircuitState.RECOVERY, consecutive_wins_in_recovery=3)
    result = evaluate_circuit_breaker(recovered, cfg)
    assert result.state is CircuitState.NORMAL
    assert result.sizing_multiplier == 1.0
    assert result.reasons == ["RECOVERY_COMPLETE_BACK_TO_NORMAL"]

    normal = CircuitBreakerState(peak_equity_usdt=900.0, current_equity_usdt=1000.0)
    result = evaluate_circuit_breaker(normal, cfg)
    assert result.state is CircuitState.NORMAL
    assert result.peak_equity_usdt == 1000.0
    assert result.sizing_multiplier == 1.0

    zero_peak = CircuitBreakerState(peak_equity_usdt=0.0, current_equity_usdt=0.0)
    result = evaluate_circuit_breaker(zero_peak, cfg)
    assert result.state is CircuitState.NORMAL


def test_record_trade_result_tracks_loss_win_recovery_and_trims(monkeypatch) -> None:
    monkeypatch.setattr(cbm.time, "time", lambda: 20_000.0)
    state = CircuitBreakerState(
        state=CircuitState.RECOVERY,
        recent_pnl_events=[(1.0, -100.0), (19_900.0, 5.0)],
    )
    result = record_trade_result(state, pnl_bps=10.0, pnl_usdt=2.0)
    assert result.current_equity_usdt == 1002.0
    assert result.session_pnl_usdt == 2.0
    assert result.consecutive_losses == 0
    assert result.consecutive_wins_in_recovery == 1
    assert result.trades_this_hour == 1
    assert result.trades_this_day == 1
    assert result.last_trade_timestamp == 20_000.0
    assert all(ts >= 16_400.0 for ts, _ in result.recent_pnl_events)

    result = record_trade_result(state, pnl_bps=-20.0, pnl_usdt=-3.0)
    assert result.current_equity_usdt == 999.0
    assert result.session_pnl_usdt == -1.0
    assert result.consecutive_losses == 1
    assert result.consecutive_wins_in_recovery == 0
