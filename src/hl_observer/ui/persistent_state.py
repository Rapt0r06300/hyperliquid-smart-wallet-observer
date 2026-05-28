from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from hl_observer.config.settings import Settings
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


STATE_VERSION = 1
STATE_FILENAME = "ui_simulation_state.json"
MAX_PERSISTED_LEDGER_EVENTS = 2_000
MAX_PERSISTED_DELTA_KEYS = 10_000


def simulation_state_path(settings: Settings) -> Path:
    db_path = _sqlite_path_from_url(settings.database_url)
    if db_path is not None:
        return db_path.parent / "runtime" / STATE_FILENAME
    return Path("data") / "runtime" / STATE_FILENAME


def load_or_create_ui_state(settings: Settings) -> UiState:
    path = simulation_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        loaded = _load_state_file(path)
        if loaded is not None:
            return loaded
    state = UiState()
    persist_simulation_state(settings, state)
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
        "simulation_closed_positions": _safe_closed_positions_payload(state.simulation_closed_positions),
        "simulation_ledger_events": _safe_ledger_payload(state.simulation_ledger_events),
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
    closed = payload.get("simulation_closed_positions")
    if isinstance(closed, list):
        state.simulation_closed_positions = [
            item
            for item in closed[-500:]
            if isinstance(item, dict)
        ]
    ledger = payload.get("simulation_ledger_events")
    if isinstance(ledger, list):
        state.simulation_ledger_events = [
            item
            for item in ledger[-MAX_PERSISTED_LEDGER_EVENTS:]
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


def _safe_closed_positions_payload(positions: list[dict]) -> list[dict]:
    safe_list: list[dict] = []
    for pos in positions[-500:]:
        if not isinstance(pos, dict):
            continue
        safe_list.append(_recursively_sanitize(pos))
    return safe_list


def _safe_position_payload(positions: dict[str, dict]) -> dict[str, dict]:
    safe: dict[str, dict] = {}
    for key, value in positions.items():
        if not isinstance(value, dict):
            continue
        safe[str(key)] = _recursively_sanitize(value)
    return safe


def _recursively_sanitize(data: dict) -> dict:
    """Safely sanitizes a dictionary for JSON persistence, ensuring nested dicts/lists are kept."""
    result = {}
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            result[k] = v
        elif isinstance(v, list):
            result[k] = [
                item if isinstance(item, (str, int, float, bool)) or item is None
                else _recursively_sanitize(item) if isinstance(item, dict)
                else str(item)
                for item in v
            ]
        elif isinstance(v, dict):
            result[k] = _recursively_sanitize(v)
        else:
            result[k] = str(v)
    return result


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
