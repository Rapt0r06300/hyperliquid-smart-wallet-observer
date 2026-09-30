from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.simulation.simulation_engine import SimulationEngine
from hyper_smart_observer.simulation.simulation_models import SimulationIntent


@dataclass(slots=True)
class ReplaySimulationResult:
    intents_seen: int
    accepted: int
    rejected: int
    final_equity: float
    drawdown: float


def replay_intents(intents: list[SimulationIntent], *, engine: SimulationEngine | None = None) -> ReplaySimulationResult:
    sim = engine or SimulationEngine()
    accepted = 0
    rejected = 0
    for intent in intents:
        decision = sim.apply(intent)
        if decision.accepted:
            accepted += 1
        else:
            rejected += 1
    return ReplaySimulationResult(
        intents_seen=len(intents),
        accepted=accepted,
        rejected=rejected,
        final_equity=round(sim.portfolio.current_equity(), 8),
        drawdown=round(sim.portfolio.max_drawdown(), 8),
    )
