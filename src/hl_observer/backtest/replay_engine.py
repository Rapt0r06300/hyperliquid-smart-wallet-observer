from __future__ import annotations
from typing import Any
from hl_observer.config.settings import Settings
from hl_observer.execution.decision_engine import UnifiedDecisionEngine

def replay_events(settings: Settings, deltas: list[Any], mid_prices: dict[str, float]) -> dict[str, Any]:
    """Replay a sequence of deltas using the UnifiedDecisionEngine."""
    engine = UnifiedDecisionEngine(settings)
    now_ms = int(max((d.exchange_ts or 0 for d in deltas), default=0))
    return engine.process_deltas(deltas, mid_prices, now_ms)

def compare_scenarios(settings: Settings, deltas: list[Any], mid_prices: dict[str, float]) -> dict[str, Any]:
    """Compare multiple simulation scenarios with different risk profiles."""
    results = {}

    # Scenario 1: Standard Prudent (default)
    results["prudent_standard"] = replay_events(settings, deltas, mid_prices)

    # Scenario 2: Aggressive (higher notional)
    agg_settings = settings.model_copy(deep=True)
    agg_settings.paper_simulation.max_position_notional = 100.0
    agg_settings.paper_simulation.max_total_exposure = 500.0
    results["aggressive_growth"] = replay_events(agg_settings, deltas, mid_prices)

    # Scenario 3: Ultra Conservative
    cons_settings = settings.model_copy(deep=True)
    cons_settings.paper_simulation.max_position_notional = 20.0
    cons_settings.paper_simulation.max_drawdown_stop_pct = 5.0
    results["conservative_safety"] = replay_events(cons_settings, deltas, mid_prices)

    return results
