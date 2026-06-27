from __future__ import annotations

from hyper_smart_observer.simulation.simulation_engine import SimulationEngine


def format_simulation_report(engine: SimulationEngine, *, title: str = "simulation=local_without_money") -> str:
    return "\n".join(
        [
            title,
            f"starting_equity={engine.portfolio.starting_equity:.2f}",
            f"current_equity={engine.portfolio.current_equity():.6f}",
            f"open_positions={len(engine.portfolio.positions)}",
            f"fills={len(engine.fills)}",
            f"decisions={len(engine.decisions)}",
            f"max_drawdown={engine.portfolio.max_drawdown():.6f}",
            "execution=forbidden",
        ]
    )
