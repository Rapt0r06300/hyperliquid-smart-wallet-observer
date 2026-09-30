from __future__ import annotations

from hyper_smart_observer.simulation.simulation_models import SimulationConfig
from hyper_smart_observer.simulation.virtual_portfolio import VirtualPortfolio


def drawdown_stop_triggered(portfolio: VirtualPortfolio, *, max_drawdown_stop_pct: float = 10.0) -> bool:
    return portfolio.max_drawdown() >= max(0.0, max_drawdown_stop_pct) / 100.0


def validate_simulation_config(config: SimulationConfig) -> list[str]:
    warnings: list[str] = []
    if config.starting_equity != 1000.0:
        warnings.append("STARTING_EQUITY_NOT_DEFAULT_1000")
    if config.max_position_notional > 50.0:
        warnings.append("MAX_POSITION_ABOVE_PRODUCT_DEFAULT")
    if config.max_total_exposure > 200.0:
        warnings.append("MAX_EXPOSURE_ABOVE_PRODUCT_DEFAULT")
    return warnings

