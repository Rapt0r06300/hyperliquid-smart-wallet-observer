"""Advanced Risk Manager — unified risk engine inspired by CloddsBot & guberm.

Provides the missing risk layers identified during the mega audit:
  1. Volatility regime detection (vol clustering -> position sizing adjustments)
  2. VaR/CVaR portfolio risk limits
  3. Per-category exposure caps (from guberm: 80% per category)
  4. Daily stop-loss halt (from guberm: 20% daily loss -> halt)
  5. Max drawdown halt (from guberm: 50% max drawdown -> kill)
  6. Alpha decay tracking (edge degrades with time/copies)
  7. Market correlation filter (correlated positions -> reduce)

SAFETY: simulation paper uniquement. Aucun ordre reel.
READ-ONLY, PAPER-ONLY, TESTNET-FIRST, DENY-BY-DEFAULT.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass


class VolatilityRegime(StrEnum):
    """Market volatility state -- drives position sizing multiplier."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class RiskVeto(StrEnum):
    """Risk veto reasons."""
    NONE = "none"
    DAILY_LOSS_HALT = "daily_loss_halt"
    MAX_DRAWDOWN_HALT = "max_drawdown_halt"
    CATEGORY_EXPOSURE_EXCEEDED = "category_exposure_exceeded"
    TOTAL_EXPOSURE_EXCEEDED = "total_exposure_exceeded"
    VAR_LIMIT_EXCEEDED = "var_limit_exceeded"
    CORRELATION_TOO_HIGH = "correlation_too_high"
    ALPHA_DECAYED = "alpha_decayed"
    VOLATILITY_EXTREME = "volatility_extreme"


@dataclass
class AdvancedRiskConfig:
    """Configuration for advanced risk manager."""
    daily_loss_halt_pct: float = 20.0
    max_drawdown_halt_pct: float = 50.0
    max_per_position_pct: float = 15.0
    max_per_category_pct: float = 80.0
    max_total_exposure_pct: float = 100.0
    max_var_pct: float = 8.0
    vol_low_threshold: float = 15.0
    vol_high_threshold: float = 45.0
    vol_extreme_threshold: float = 80.0
    vol_high_sizing_mult: float = 0.60
    vol_extreme_sizing_mult: float = 0.30
    alpha_decay_max_hours: float = 4.0
    max_correlation: float = 0.85
    starting_equity_usdt: float = 1000.0


@dataclass
class DailyPnLState:
    """Tracks daily PnL for stop-loss halt."""
    day_start_equity_usdt: float = 1000.0
    day_realized_pnl_usdt: float = 0.0
    day_start_timestamp: float = 0.0
    trades_today: int = 0


@dataclass
class VolatilityState:
    """Recent price returns for vol estimation."""
    recent_returns: list = field(default_factory=list)
    max_window: int = 100
    current_regime: VolatilityRegime = VolatilityRegime.NORMAL
    last_computed_at: float = 0.0
    annualized_vol_pct: float = 25.0

    def add_return(self, ret_pct: float) -> None:
        self.recent_returns.append(ret_pct)
        if len(self.recent_returns) > self.max_window:
            self.recent_returns = self.recent_returns[-self.max_window:]


@dataclass
class RiskAssessment:
    """Result of risk evaluation."""
    allowed: bool = True
    veto: RiskVeto = RiskVeto.NONE
    reasons: list = field(default_factory=list)
    sizing_multiplier: float = 1.0
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    current_var_pct: float = 0.0
    category_exposure_pct: float = 0.0
    total_exposure_pct: float = 0.0


@dataclass
class AdvancedRiskManager:
    """Unified risk engine with all viral bot risk layers.

    PAPER SIMULATION ONLY. No real orders ever.
    """
    config: AdvancedRiskConfig = field(default_factory=AdvancedRiskConfig)
    daily_state: DailyPnLState = field(default_factory=DailyPnLState)
    vol_state: VolatilityState = field(default_factory=VolatilityState)
    peak_equity_usdt: float = 0.0
    current_equity_usdt: float = 0.0
    category_exposures: dict = field(default_factory=dict)
    open_positions_coins: list = field(default_factory=list)
    signal_first_seen: dict = field(default_factory=dict)
    total_vetoes: int = 0
    veto_counts: dict = field(default_factory=lambda: {
        v.value: 0 for v in RiskVeto if v != RiskVeto.NONE
    })

    def initialize(self, starting_equity: float) -> None:
        self.config.starting_equity_usdt = starting_equity
        self.peak_equity_usdt = starting_equity
        self.current_equity_usdt = starting_equity
        self.daily_state.day_start_equity_usdt = starting_equity
        self.daily_state.day_start_timestamp = time.time()

    def update_equity(self, new_equity: float) -> None:
        self.current_equity_usdt = new_equity
        if new_equity > self.peak_equity_usdt:
            self.peak_equity_usdt = new_equity

    def record_daily_pnl(self, pnl_usdt: float) -> None:
        now = time.time()
        if now - self.daily_state.day_start_timestamp > 86400:
            self.daily_state.day_start_equity_usdt = self.current_equity_usdt
            self.daily_state.day_realized_pnl_usdt = 0.0
            self.daily_state.day_start_timestamp = now
            self.daily_state.trades_today = 0
        self.daily_state.day_realized_pnl_usdt += pnl_usdt
        self.daily_state.trades_today += 1

    def update_volatility(self, price_return_pct: float) -> None:
        self.vol_state.add_return(price_return_pct)
        if len(self.vol_state.recent_returns) >= 5:
            self._recompute_vol_regime()

    def _recompute_vol_regime(self) -> None:
        returns = self.vol_state.recent_returns
        if len(returns) < 5:
            return
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(max(0, variance))
        periods_per_year = 14400 * 252
        ann_vol = std_return * math.sqrt(periods_per_year) * 100
        self.vol_state.annualized_vol_pct = ann_vol
        self.vol_state.last_computed_at = time.time()
        if ann_vol >= self.config.vol_extreme_threshold:
            self.vol_state.current_regime = VolatilityRegime.EXTREME
        elif ann_vol >= self.config.vol_high_threshold:
            self.vol_state.current_regime = VolatilityRegime.HIGH
        elif ann_vol <= self.config.vol_low_threshold:
            self.vol_state.current_regime = VolatilityRegime.LOW
        else:
            self.vol_state.current_regime = VolatilityRegime.NORMAL

    def compute_var_95(self, positions_notional: list) -> float:
        if not positions_notional:
            return 0.0
        total_exposure = sum(abs(n) for n in positions_notional)
        daily_vol = self.vol_state.annualized_vol_pct / math.sqrt(252) / 100
        var_usdt = total_exposure * daily_vol * 1.645
        equity = max(1.0, self.current_equity_usdt)
        return (var_usdt / equity) * 100

    def evaluate_risk(
        self,
        *,
        coin: str,
        proposed_notional_usdt: float,
        category: str = "perpetual",
        current_open_notionals: list = None,
        signal_id: str = None,
    ) -> RiskAssessment:
        reasons = []
        sizing_mult = 1.0
        equity = max(1.0, self.current_equity_usdt)

        # 1. Daily stop-loss
        daily_pnl_pct = (self.daily_state.day_realized_pnl_usdt / max(1.0, self.daily_state.day_start_equity_usdt)) * 100
        if daily_pnl_pct <= -self.config.daily_loss_halt_pct:
            self.total_vetoes += 1
            self.veto_counts[RiskVeto.DAILY_LOSS_HALT.value] += 1
            return RiskAssessment(
                allowed=False, veto=RiskVeto.DAILY_LOSS_HALT,
                reasons=[f"daily_loss_{abs(daily_pnl_pct):.1f}pct"], daily_pnl_pct=daily_pnl_pct)

        # 2. Max drawdown
        drawdown_pct = ((self.peak_equity_usdt - self.current_equity_usdt) / max(1.0, self.peak_equity_usdt)) * 100
        if drawdown_pct >= self.config.max_drawdown_halt_pct:
            self.total_vetoes += 1
            self.veto_counts[RiskVeto.MAX_DRAWDOWN_HALT.value] += 1
            return RiskAssessment(
                allowed=False, veto=RiskVeto.MAX_DRAWDOWN_HALT,
                reasons=[f"drawdown_{drawdown_pct:.1f}pct"], drawdown_pct=drawdown_pct, daily_pnl_pct=daily_pnl_pct)

        # 3. Per-position cap
        max_position = equity * self.config.max_per_position_pct / 100
        if proposed_notional_usdt > max_position:
            proposed_notional_usdt = max_position
            reasons.append("capped_per_position")

        # 4. Total exposure
        open_notionals = current_open_notionals or []
        current_total = sum(abs(n) for n in open_notionals)
        total_after = current_total + proposed_notional_usdt
        total_exposure_pct = (total_after / equity) * 100
        if total_exposure_pct > self.config.max_total_exposure_pct:
            self.total_vetoes += 1
            self.veto_counts[RiskVeto.TOTAL_EXPOSURE_EXCEEDED.value] += 1
            return RiskAssessment(
                allowed=False, veto=RiskVeto.TOTAL_EXPOSURE_EXCEEDED,
                reasons=["total_exposure_exceeded"], total_exposure_pct=total_exposure_pct,
                drawdown_pct=drawdown_pct, daily_pnl_pct=daily_pnl_pct)

        # 5. Category exposure
        cat_exposure = self.category_exposures.get(category, 0.0) + proposed_notional_usdt
        cat_pct = (cat_exposure / equity) * 100
        if cat_pct > self.config.max_per_category_pct:
            self.total_vetoes += 1
            self.veto_counts[RiskVeto.CATEGORY_EXPOSURE_EXCEEDED.value] += 1
            return RiskAssessment(
                allowed=False, veto=RiskVeto.CATEGORY_EXPOSURE_EXCEEDED,
                reasons=["category_exposure_exceeded"], category_exposure_pct=cat_pct,
                total_exposure_pct=total_exposure_pct, drawdown_pct=drawdown_pct, daily_pnl_pct=daily_pnl_pct)

        # 6. VaR
        test_notionals = open_notionals + [proposed_notional_usdt]
        var_pct = self.compute_var_95(test_notionals)
        if var_pct > self.config.max_var_pct:
            self.total_vetoes += 1
            self.veto_counts[RiskVeto.VAR_LIMIT_EXCEEDED.value] += 1
            return RiskAssessment(
                allowed=False, veto=RiskVeto.VAR_LIMIT_EXCEEDED,
                reasons=["var_exceeded"], current_var_pct=var_pct,
                total_exposure_pct=total_exposure_pct, drawdown_pct=drawdown_pct, daily_pnl_pct=daily_pnl_pct)

        # 7. Volatility regime sizing
        regime = self.vol_state.current_regime
        if regime == VolatilityRegime.EXTREME:
            sizing_mult *= self.config.vol_extreme_sizing_mult
            reasons.append("extreme_vol_sizing")
        elif regime == VolatilityRegime.HIGH:
            sizing_mult *= self.config.vol_high_sizing_mult
            reasons.append("high_vol_sizing")

        # 8. Alpha decay
        if signal_id:
            now = time.time()
            first_seen = self.signal_first_seen.get(signal_id)
            if first_seen is None:
                self.signal_first_seen[signal_id] = now
            else:
                age_hours = (now - first_seen) / 3600
                if age_hours > self.config.alpha_decay_max_hours:
                    self.total_vetoes += 1
                    self.veto_counts[RiskVeto.ALPHA_DECAYED.value] += 1
                    return RiskAssessment(
                        allowed=False, veto=RiskVeto.ALPHA_DECAYED,
                        reasons=["alpha_decayed"], volatility_regime=regime,
                        drawdown_pct=drawdown_pct, daily_pnl_pct=daily_pnl_pct)

        # 9. Correlation filter
        if coin.upper() in self.open_positions_coins:
            coin_count = self.open_positions_coins.count(coin.upper())
            if coin_count >= 2:
                reasons.append("correlated_positions")
                sizing_mult *= 0.5

        return RiskAssessment(
            allowed=True, veto=RiskVeto.NONE, reasons=reasons,
            sizing_multiplier=sizing_mult, volatility_regime=regime,
            daily_pnl_pct=daily_pnl_pct, drawdown_pct=drawdown_pct,
            current_var_pct=var_pct, category_exposure_pct=cat_pct,
            total_exposure_pct=total_exposure_pct)

    def on_position_opened(self, coin: str, notional: float, category: str = "perpetual") -> None:
        self.open_positions_coins.append(coin.upper())
        self.category_exposures[category] = self.category_exposures.get(category, 0.0) + abs(notional)

    def on_position_closed(self, coin: str, notional: float, pnl_usdt: float, category: str = "perpetual") -> None:
        coin_upper = coin.upper()
        if coin_upper in self.open_positions_coins:
            self.open_positions_coins.remove(coin_upper)
        cat_exp = self.category_exposures.get(category, 0.0) - abs(notional)
        self.category_exposures[category] = max(0.0, cat_exp)
        self.record_daily_pnl(pnl_usdt)
        self.update_equity(self.current_equity_usdt + pnl_usdt)

    def get_risk_report(self) -> dict:
        equity = max(1.0, self.current_equity_usdt)
        drawdown_pct = ((self.peak_equity_usdt - self.current_equity_usdt) / max(1.0, self.peak_equity_usdt)) * 100
        daily_pnl_pct = (self.daily_state.day_realized_pnl_usdt / max(1.0, self.daily_state.day_start_equity_usdt)) * 100
        return {
            "current_equity_usdt": round(self.current_equity_usdt, 2),
            "peak_equity_usdt": round(self.peak_equity_usdt, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "daily_pnl_usdt": round(self.daily_state.day_realized_pnl_usdt, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "trades_today": self.daily_state.trades_today,
            "volatility_regime": self.vol_state.current_regime.value,
            "annualized_vol_pct": round(self.vol_state.annualized_vol_pct, 1),
            "category_exposures": {k: round(v, 2) for k, v in self.category_exposures.items()},
            "open_position_coins": list(self.open_positions_coins),
            "total_vetoes": self.total_vetoes,
            "veto_breakdown": dict(self.veto_counts),
            "simulation_only": True,
            "real_orders_created": 0,
        }

    def cleanup_old_signals(self, max_age_hours: float = 24.0) -> int:
        now = time.time()
        cutoff = now - max_age_hours * 3600
        old_ids = [sid for sid, ts in self.signal_first_seen.items() if ts < cutoff]
        for sid in old_ids:
            del self.signal_first_seen[sid]
        return len(old_ids)
