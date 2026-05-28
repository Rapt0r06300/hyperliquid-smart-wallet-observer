from __future__ import annotations

from typing import Any
from hl_observer.execution.decision_engine import UnifiedDecisionEngine, SimulationConfig, SimulationState


def replay_events(
    deltas: list[Any],
    mid_prices: dict[str, float] | list[dict[str, Any]],
    config: SimulationConfig,
) -> SimulationState:
    """Replays historical delta events with realistic latency and dynamic price discovery."""
    engine = UnifiedDecisionEngine(config)
    state = SimulationState(starting_equity_usdt=config.starting_equity_usdt)
    state.equity_usdt = config.starting_equity_usdt

    # Pre-sort historical snapshots if provided as a list
    snapshots = []
    if isinstance(mid_prices, list):
        snapshots = sorted(mid_prices, key=lambda x: int(x.get("timestamp_ms") or 0))

    def get_mids_at(ts: int) -> dict[str, float]:
        if not snapshots: return mid_prices if isinstance(mid_prices, dict) else {}
        # Find the latest snapshot before or at ts
        best = snapshots[0].get("mids", {})
        for s in snapshots:
            if int(s.get("timestamp_ms") or 0) > ts: break
            best = s.get("mids", {})
        return best

    # Enforce chronological processing
    sorted_deltas = sorted(deltas, key=lambda x: int(getattr(x, 'exchange_ts', 0) or getattr(x, 'detected_at_ms', 0) or 0))

    poll_ms = 0
    if config.mode == "POLLING_60S": poll_ms = 60_000
    elif config.mode == "POLLING_300S": poll_ms = 300_000

    last_poll = 0
    for row in sorted_deltas:
        event_ms = int(getattr(row, 'exchange_ts', 0) or getattr(row, 'detected_at_ms', 0) or 0)

        if poll_ms > 0:
            if event_ms >= last_poll:
                curr_ms = ((event_ms // poll_ms) + 1) * poll_ms
                last_poll = curr_ms
            else: curr_ms = last_poll
        else:
            curr_ms = event_ms + 50

        mids = get_mids_at(curr_ms)
        engine.process_delta(row, curr_ms, mids, state, sorted_deltas)

    return state


def run_scenario_comparison(
    deltas: list[Any],
    mid_prices: dict[str, float] | list[dict[str, Any]],
    base_config: SimulationConfig
) -> dict[str, SimulationState]:
    """Compares multiple simulation scenarios to identify optimal strategies."""
    scenarios = {
        "WS_LIKE": _mod(base_config, mode="WS_LIKE"),
        "POLLING_60S": _mod(base_config, mode="POLLING_60S"),
        "POLLING_300S": _mod(base_config, mode="POLLING_300S"),
        "OPEN_ONLY": _mod(base_config, open_only=True),
        "CONSENSUS_REQUIRED": _mod(base_config, consensus_required=True),
        "STRICT_EDGE": _mod(base_config, strict_edge=True),
        "LOOSE_EDGE": _mod(base_config, strict_edge=False, min_edge_required_bps=2.0),
    }

    return {name: replay_events(deltas, mid_prices, cfg) for name, cfg in scenarios.items()}


def _mod(config: SimulationConfig, **kwargs) -> SimulationConfig:
    new_cfg = config.model_copy(deep=True)
    for k, v in kwargs.items():
        if hasattr(new_cfg, k): setattr(new_cfg, k, v)
    if "min_edge_required_bps" in kwargs:
        new_cfg.risk_config.min_edge_required_bps = kwargs["min_edge_required_bps"]
    return new_cfg
