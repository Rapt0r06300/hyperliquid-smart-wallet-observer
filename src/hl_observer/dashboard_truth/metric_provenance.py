from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricProvenance:
    metric: str
    json_path: str
    expected_source: str
    beginner_label: str


REQUIRED_SIMULATION_METRICS: tuple[MetricProvenance, ...] = (
    MetricProvenance("starting_equity_usdt", "equity.starting_equity_usdt", "simulation_snapshot", "Capital de depart"),
    MetricProvenance("current_equity_usdt", "equity.current_equity_usdt", "simulation_snapshot", "Solde actuel"),
    MetricProvenance("current_pnl_usdc", "equity.current_pnl_usdc", "simulation_snapshot", "Gain/perte actuel"),
    MetricProvenance("realized_pnl_usdc", "equity.realized_pnl_usdc", "simulation_snapshot", "Gain/perte deja ferme"),
    MetricProvenance("unrealized_pnl_usdc", "equity.unrealized_pnl_usdc", "simulation_snapshot", "Gain/perte des positions ouvertes"),
    MetricProvenance("open_exposure_usdt", "equity.open_exposure_usdt", "simulation_snapshot", "Montant encore expose"),
    MetricProvenance("ledger_events", "bot_simulation.ledger_events", "simulation_snapshot", "Journal des decisions"),
)


def get_nested(payload: dict, dotted_path: str):
    current = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current

