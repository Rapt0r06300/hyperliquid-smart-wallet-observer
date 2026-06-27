from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.simulation.simulation_engine import SimulationEngine
from hyper_smart_observer.simulation.simulation_models import (
    SimulationConfig,
    SimulationDecision,
)
from hyper_smart_observer.simulation.simulation_report import format_simulation_report


@dataclass(slots=True)
class ScenarioResult:
    scenario: str
    engine: SimulationEngine
    report: str


def run_conservative_scenario(*, capital: float = 1000.0) -> ScenarioResult:
    """Run a deterministic protection-mode scenario for smoke tests and CLI checks.

    This command is often used by humans as a quick "does the simulation work?"
    check. It must not create a fake losing trade or a fake winning trade. Without
    fresh measured edge, the safest deterministic behavior is no-trade at exactly
    the starting equity.
    """

    engine = SimulationEngine(config=SimulationConfig(starting_equity=capital))
    engine.decisions.append(
        SimulationDecision(
            accepted=False,
            reason="EDGE_UNPROVEN_PROTECTION_MODE",
            message="No fresh measurable edge was provided; capital is preserved at 1000 USDT. No order was created.",
        )
    )
    return ScenarioResult(
        scenario="conservative",
        engine=engine,
        report=format_simulation_report(engine, title="simulate_magic_bot=local_no_money"),
    )
