from __future__ import annotations

import time

import pytest

from hl_observer.risk.advanced_risk_manager import (
    AdvancedRiskConfig,
    AdvancedRiskManager,
    RiskVeto,
    VolatilityRegime,
    VolatilityState,
)


def _manager(**config_overrides) -> AdvancedRiskManager:
    cfg = AdvancedRiskConfig(**config_overrides)
    manager = AdvancedRiskManager(config=cfg)
    manager.initialize(1000.0)
    return manager


def test_volatility_state_window_and_all_regimes() -> None:
    state = VolatilityState(max_window=3)
    for value in (1.0, 2.0, 3.0, 4.0):
        state.add_return(value)
    assert state.recent_returns == [2.0, 3.0, 4.0]

    manager = _manager()
    manager.vol_state.recent_returns = [0.0] * 5
    manager._recompute_vol_regime()
    assert manager.vol_state.current_regime is VolatilityRegime.LOW

    samples = [0.0, 1.0, 0.0, 1.0, 0.0]
    manager.vol_state.recent_returns = samples
    manager.config.vol_low_threshold = -1.0
    manager.config.vol_high_threshold = 1e12
    manager.config.vol_extreme_threshold = 2e12
    manager._recompute_vol_regime()
    assert manager.vol_state.current_regime is VolatilityRegime.NORMAL

    manager.config.vol_high_threshold = 1.0
    manager.config.vol_extreme_threshold = 2e12
    manager._recompute_vol_regime()
    assert manager.vol_state.current_regime is VolatilityRegime.HIGH

    manager.config.vol_extreme_threshold = 1.0
    manager._recompute_vol_regime()
    assert manager.vol_state.current_regime is VolatilityRegime.EXTREME
    assert manager.vol_state.last_computed_at > 0
    assert manager.vol_state.annualized_vol_pct > 0


def test_equity_daily_pnl_var_and_daily_reset() -> None:
    manager = _manager()
    manager.update_equity(1100.0)
    assert manager.current_equity_usdt == 1100.0
    assert manager.peak_equity_usdt == 1100.0
    manager.update_equity(1050.0)
    assert manager.peak_equity_usdt == 1100.0

    manager.record_daily_pnl(10.0)
    assert manager.daily_state.day_realized_pnl_usdt == 10.0
    assert manager.daily_state.trades_today == 1
    manager.daily_state.day_start_timestamp = time.time() - 90_000
    manager.current_equity_usdt = 1050.0
    manager.record_daily_pnl(-5.0)
    assert manager.daily_state.day_start_equity_usdt == 1050.0
    assert manager.daily_state.day_realized_pnl_usdt == -5.0
    assert manager.daily_state.trades_today == 1

    assert manager.compute_var_95([]) == 0.0
    assert manager.compute_var_95([100.0, -50.0]) > 0.0


def test_risk_vetoes_daily_loss_drawdown_total_category_and_var() -> None:
    daily = _manager()
    daily.daily_state.day_realized_pnl_usdt = -250.0
    result = daily.evaluate_risk(coin="BTC", proposed_notional_usdt=50.0)
    assert result.allowed is False and result.veto is RiskVeto.DAILY_LOSS_HALT

    drawdown = _manager()
    drawdown.current_equity_usdt = 400.0
    result = drawdown.evaluate_risk(coin="BTC", proposed_notional_usdt=10.0)
    assert result.allowed is False and result.veto is RiskVeto.MAX_DRAWDOWN_HALT

    total = _manager(max_total_exposure_pct=100.0)
    result = total.evaluate_risk(
        coin="BTC", proposed_notional_usdt=200.0, current_open_notionals=[900.0]
    )
    assert result.allowed is False and result.veto is RiskVeto.TOTAL_EXPOSURE_EXCEEDED

    category = _manager(max_per_category_pct=80.0)
    category.category_exposures["perpetual"] = 750.0
    result = category.evaluate_risk(coin="BTC", proposed_notional_usdt=100.0)
    assert result.allowed is False and result.veto is RiskVeto.CATEGORY_EXPOSURE_EXCEEDED

    var = _manager(max_var_pct=0.001)
    result = var.evaluate_risk(coin="BTC", proposed_notional_usdt=100.0)
    assert result.allowed is False and result.veto is RiskVeto.VAR_LIMIT_EXCEEDED


def test_risk_sizing_cap_volatility_alpha_and_correlation_paths() -> None:
    capped = _manager(max_var_pct=100.0)
    result = capped.evaluate_risk(coin="ETH", proposed_notional_usdt=999.0)
    assert result.allowed is True
    assert "capped_per_position" in result.reasons

    high = _manager(max_var_pct=100.0)
    high.vol_state.current_regime = VolatilityRegime.HIGH
    result = high.evaluate_risk(coin="SOL", proposed_notional_usdt=50.0)
    assert result.allowed is True
    assert result.sizing_multiplier == pytest.approx(high.config.vol_high_sizing_mult)
    assert "high_vol_sizing" in result.reasons

    extreme = _manager(max_var_pct=100.0)
    extreme.vol_state.current_regime = VolatilityRegime.EXTREME
    result = extreme.evaluate_risk(coin="SOL", proposed_notional_usdt=50.0)
    assert result.allowed is True
    assert result.sizing_multiplier == pytest.approx(extreme.config.vol_extreme_sizing_mult)
    assert "extreme_vol_sizing" in result.reasons

    alpha = _manager(max_var_pct=100.0, alpha_decay_max_hours=1.0)
    first = alpha.evaluate_risk(coin="HYPE", proposed_notional_usdt=50.0, signal_id="sig")
    assert first.allowed is True and "sig" in alpha.signal_first_seen
    alpha.signal_first_seen["sig"] = time.time() - 7200
    expired = alpha.evaluate_risk(coin="HYPE", proposed_notional_usdt=50.0, signal_id="sig")
    assert expired.allowed is False and expired.veto is RiskVeto.ALPHA_DECAYED

    correlated = _manager(max_var_pct=100.0)
    correlated.open_positions_coins[:] = ["BTC", "BTC"]
    result = correlated.evaluate_risk(coin="btc", proposed_notional_usdt=50.0)
    assert result.allowed is True
    assert result.sizing_multiplier == pytest.approx(0.5)
    assert "correlated_positions" in result.reasons


def test_position_lifecycle_report_cleanup_and_update_volatility() -> None:
    manager = _manager(max_var_pct=100.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    manager.update_volatility(0.0)
    assert manager.vol_state.current_regime is VolatilityRegime.LOW

    manager.on_position_opened("btc", 100.0)
    assert manager.open_positions_coins == ["BTC"]
    assert manager.category_exposures["perpetual"] == 100.0
    manager.on_position_closed("btc", 100.0, 5.0)
    assert manager.open_positions_coins == []
    assert manager.category_exposures["perpetual"] == 0.0
    assert manager.current_equity_usdt == 1005.0

    report = manager.get_risk_report()
    assert report["simulation_only"] is True
    assert report["real_orders_created"] == 0
    assert report["current_equity_usdt"] == 1005.0

    manager.signal_first_seen = {
        "old": time.time() - 100_000,
        "new": time.time(),
    }
    assert manager.cleanup_old_signals(max_age_hours=24.0) == 1
    assert set(manager.signal_first_seen) == {"new"}
