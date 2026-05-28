from __future__ import annotations


from typing import Any
from hl_observer.execution.decision_engine import DecisionContext, UnifiedDecisionEngine
from hl_observer.storage.models import PositionDeltaModel

class ReplayEngine:
    def __init__(self, settings: Any):
        self.settings = settings
        self.decision_engine = UnifiedDecisionEngine(settings)

    def replay_wallet_deltas(self, deltas: list[PositionDeltaModel], *, initial_equity: float = 1000.0) -> dict[str, Any]:
        equity = initial_equity
        # Note: Implementation logic would follow src/hl_observer/ui/routes.py build_bot_simulation
        # but using the unified decision engine for consistency.
        return {"final_equity": equity, "deltas_processed": len(deltas)}


def replay_events(raw_events: list[dict]) -> list[dict]:
    return list(raw_events)
