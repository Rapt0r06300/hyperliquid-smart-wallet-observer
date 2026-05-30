from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.ui.schemas import UiEvent, UiLogLine, VirtualPosition
from hl_observer.utils.time import now_ms


@dataclass(slots=True)
class UiState:
    kill_switch_active: bool = False
    discovery_running: bool = False
    autoscan_started: bool = False
    autoscan_running: bool = False
    autoscan_current_step: str = "En attente"
    autoscan_progress_percent: float = 0.0
    last_discovery_state: str = "idle"
    last_discovery_error: str | None = None
    last_autoscan_summary: dict = field(default_factory=dict)
    events: list[UiEvent] = field(default_factory=list)
    logs: list[UiLogLine] = field(default_factory=list)
    max_events: int = 250
    max_logs: int = 500
    simulation_started_at_ms: int = field(default_factory=now_ms)
    simulation_starting_equity_usdt: float = 1000.0
    simulation_processed_delta_keys: set[str] = field(default_factory=set)
    simulation_virtual_positions: dict[str, VirtualPosition | dict[str, Any]] = field(default_factory=dict)
    simulation_closed_positions: list[VirtualPosition | dict[str, Any]] = field(default_factory=list)
    simulation_ledger_events: list[dict[str, Any]] = field(default_factory=list)
    simulation_drawdown_stop_active: bool = False

    def add_event(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "INFO",
        payload: dict | None = None,
    ) -> UiEvent:
        event = UiEvent(
            event_type=event_type,
            message=message,
            level=level,  # type: ignore[arg-type]
            timestamp_ms=now_ms(),
            payload=payload or {},
        )
        self.events.append(event)
        self.events[:] = self.events[-self.max_events :]
        self.add_log(message, level=level, context={"event_type": event_type, **(payload or {})})
        return event

    def add_log(
        self,
        message: str,
        *,
        level: str = "INFO",
        context: dict | None = None,
    ) -> UiLogLine:
        log = UiLogLine(
            level=level,  # type: ignore[arg-type]
            message=message,
            timestamp_ms=now_ms(),
            context=context or {},
        )
        self.logs.append(log)
        self.logs[:] = self.logs[-self.max_logs :]
        return log

    def clear_logs(self) -> None:
        self.logs.clear()
        self.events.clear()
        self.simulation_virtual_positions.clear()
        self.simulation_closed_positions.clear()
        self.simulation_ledger_events.clear()
