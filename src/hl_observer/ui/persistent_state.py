from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from hl_observer.config.settings import Settings
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


STATE_VERSION = 1
STATE_FILENAME = "ui_simulation_state.json"
MAX_PERSISTED_LEDGER_EVENTS = 20_000
MAX_PERSISTED_DELTA_KEYS = 10_000
MAX_PERSISTED_EQUITY_POINTS = 5_000


def simulation_state_path(settings: Settings) -> Path:
    db_path = _sqlite_path_from_url(settings.database_url)
    if db_path is not None:
        db_parent = db_path.parent
        if db_parent.name.lower() == "data" and db_parent.parent.name.lower() == "runtime":
            return db_parent / STATE_FILENAME
        return db_parent / "runtime" / STATE_FILENAME
    return Path("data") / "runtime" / STATE_FILENAME


def load_or_create_ui_state(settings: Settings) -> UiState:
    path = simulation_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        loaded = _load_state_file(path)
        if loaded is not None:
            return loaded
    state = UiState()
    try:
        persist_simulation_state(settings, state)
    except OSError as exc:
        state.add_event(
            "simulation_state_persist_unavailable",
            "Etat simulation non persiste: le dossier runtime n'est pas inscriptible.",
            payload={"state_path": str(path), "error": str(exc)},
        )
    return state


def reset_simulation_state(settings: Settings, *, starting_equity_usdt: float = 1000.0) -> UiState:
    """Start a fresh launcher session while keeping the reset local and explicit."""

    state = UiState()
    state.simulation_started_at_ms = now_ms()
    state.simulation_starting_equity_usdt = max(1.0, float(starting_equity_usdt))
    state.simulation_equity_history = [
        _initial_equity_point(state.simulation_started_at_ms, state.simulation_starting_equity_usdt)
    ]
    try:
        persist_simulation_state(settings, state)
    except OSError as exc:
        state.add_event(
            "simulation_state_persist_unavailable",
            "Etat simulation non persiste apres reset: le dossier runtime n'est pas inscriptible.",
            payload={"state_path": str(simulation_state_path(settings)), "error": str(exc)},
        )
    return state


def persist_simulation_state(settings: Settings, state: UiState) -> Path:
    path = simulation_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "simulation_started_at_ms": int(state.simulation_started_at_ms),
        "simulation_starting_equity_usdt": float(state.simulation_starting_equity_usdt),
        "simulation_processed_delta_keys": sorted(state.simulation_processed_delta_keys)[-MAX_PERSISTED_DELTA_KEYS:],
        "simulation_virtual_positions": _safe_position_payload(state.simulation_virtual_positions),
        "simulation_ledger_events": _safe_ledger_payload(state.simulation_ledger_events),
        "simulation_realized_pnl_usdc": float(state.simulation_realized_pnl_usdc),
        "simulation_entry_costs_paid_usdc": float(state.simulation_entry_costs_paid_usdc),
        "simulation_exit_costs_paid_usdc": float(state.simulation_exit_costs_paid_usdc),
        "simulation_reproduced_entries_total": int(state.simulation_reproduced_entries_total),
        "simulation_reproduced_exits_total": int(state.simulation_reproduced_exits_total),
        "simulation_equity_history": _safe_equity_history_payload(state.simulation_equity_history),
        "updated_at_ms": now_ms(),
        "runtime_only": True,
        "notes": "Local UI simulation session state. No secrets, no orders.",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _load_state_file(path: Path) -> UiState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    started = _safe_int(payload.get("simulation_started_at_ms"))
    equity = _safe_float(payload.get("simulation_starting_equity_usdt"))
    if started is None or started <= 0:
        return None
    state = UiState()
    state.simulation_started_at_ms = started
    if equity is not None and equity > 0:
        state.simulation_starting_equity_usdt = equity
    keys = payload.get("simulation_processed_delta_keys")
    if isinstance(keys, list):
        state.simulation_processed_delta_keys = {str(item) for item in keys if item}
    positions = payload.get("simulation_virtual_positions")
    if isinstance(positions, dict):
        state.simulation_virtual_positions = {
            str(key): value
            for key, value in positions.items()
            if isinstance(value, dict)
        }
    ledger = payload.get("simulation_ledger_events")
    if isinstance(ledger, list):
        state.simulation_ledger_events = [
            item
            for item in ledger[-MAX_PERSISTED_LEDGER_EVENTS:]
            if isinstance(item, dict)
        ]
    state.simulation_realized_pnl_usdc = _safe_float(payload.get("simulation_realized_pnl_usdc")) or 0.0
    state.simulation_entry_costs_paid_usdc = _safe_float(payload.get("simulation_entry_costs_paid_usdc")) or 0.0
    state.simulation_exit_costs_paid_usdc = _safe_float(payload.get("simulation_exit_costs_paid_usdc")) or 0.0
    state.simulation_reproduced_entries_total = _safe_int(payload.get("simulation_reproduced_entries_total")) or 0
    state.simulation_reproduced_exits_total = _safe_int(payload.get("simulation_reproduced_exits_total")) or 0
    equity_history = payload.get("simulation_equity_history")
    if isinstance(equity_history, list):
        state.simulation_equity_history = [
            item
            for item in equity_history[-MAX_PERSISTED_EQUITY_POINTS:]
            if isinstance(item, dict)
        ]
    state.add_event(
        "simulation_state_restored",
        "Session simulation restauree depuis data/runtime; le PnL ne repart pas a zero apres reconnexion.",
        payload={"state_path": str(path), "simulation_started_at_ms": started},
    )
    return state


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url[len(prefix) :]
    if raw_path in {":memory:", ""}:
        return None
    return Path(unquote(raw_path)).resolve()


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_position_payload(positions: dict[str, dict]) -> dict[str, dict]:
    safe: dict[str, dict] = {}
    for key, value in positions.items():
        if not isinstance(value, dict):
            continue
        safe[str(key)] = {
            item_key: item_value
            for item_key, item_value in value.items()
            if isinstance(item_value, (str, int, float, bool)) or item_value is None
        }
    return safe


def _safe_ledger_payload(events: list[dict]) -> list[dict]:
    safe_events: list[dict] = []
    for event in events[-MAX_PERSISTED_LEDGER_EVENTS:]:
        if not isinstance(event, dict):
            continue
        safe_events.append(
            {
                key: value
                for key, value in event.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
        )
    return safe_events


def _safe_equity_history_payload(points: list[dict]) -> list[dict]:
    safe_points: list[dict] = []
    for point in points[-MAX_PERSISTED_EQUITY_POINTS:]:
        if not isinstance(point, dict):
            continue
        safe_points.append(
            {
                key: value
                for key, value in point.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
        )
    return safe_points


def _initial_equity_point(timestamp_ms: int, starting_equity_usdt: float) -> dict[str, float | int | str]:
    return {
        "timestamp_ms": int(timestamp_ms),
        "current_pnl_usdc": 0.0,
        "current_equity_usdt": float(starting_equity_usdt),
        "realized_pnl_usdc": 0.0,
        "unrealized_pnl_usdc": 0.0,
        "open_exposure_usdt": 0.0,
        "source": "SESSION_START",
    }
