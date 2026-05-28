from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, DeltaAction
from datetime import datetime, UTC, timedelta

class ScenarioRunner:
    """
    Helper to run a multi-step scenario through the HyperSmart logic.
    """
    def __init__(self, scenario_path: Path):
        with open(scenario_path, "r") as f:
            self.data = json.load(f)
        self.current_step = 0

    def get_deltas(self) -> list[LeaderDelta]:
        deltas = []
        wallet = self.data["wallet"]
        coin = self.data["coin"]

        for i, step in enumerate(self.data.get("steps", [])):
            deltas.append(LeaderDelta(
                delta_id=f"step_{i}",
                leader_wallet=wallet,
                coin=coin,
                action_type=DeltaAction(step["action"]),
                observed_at=datetime.fromtimestamp(step["timestamp_ms"]/1000, UTC),
                current_size=step.get("size"),
                leader_reference_price=step.get("price")
            ))
        return deltas

    def run_full_cycle(self, engine_callback):
        """Runs the entire scenario through the provided callback."""
        deltas = self.get_deltas()
        return engine_callback(self.data["wallet"], deltas)
