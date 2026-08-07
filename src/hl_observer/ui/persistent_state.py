from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import unquote

from hl_observer.config.settings import Settings
from hl_observer.simulation.accounting_truth import first_not_none
from hl_observer.simulation.ledger_integrity import (
    GENESIS_HASH,
    LEDGER_CORRUPTED,
    LEDGER_OK,
    RECOVERY_REQUIRED,
    latest_checkpoint,
    read_chain,
    write_chain_atomic,
)
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


STATE_VERSION = 1
STATE_FILENAME = "ui_simulation_state.json"
LEDGER_FILENAME = "ui_simulation_ledger.jsonl"
# Display projections may be bounded, but the canonical accounting ledger may
# not be truncated: risk budgets, opens_today, attribution and recovery depend
# on its complete event sequence.
MAX_PERSISTED_LEDGER_EVENTS = 20_000
MAX_PERSISTED_DELTA_KEYS = 10_000
MAX_PERSISTED_EQUITY_POINTS = 5_000


def simulation_state_path(settings: Settings) -> Path:
    explicit_dir = os.getenv("HYPERSMART_UI_STATE_DIR")
    if explicit_dir:
        return Path(explicit_dir).expanduser().resolve() / STATE_FILENAME
    db_path = _sqlite_path_from_url(settings.database_url)
    if db_path is not None:
        db_parent = db_path.parent
        if db_parent.name.lower() == "data" and db_parent.parent.name.lower() == "runtime":
            return db_parent / STATE_FILENAME
        return db_parent / "runtime" / STATE_FILENAME
    return Path("data") / "runtime" / STATE_FILENAME


def simulation_ledger_path(settings: Settings) -> Path:
    return simulation_state_path(settings).with_name(LEDGER_FILENAME)


def load_or_create_ui_state(settings: Settings) -> UiState:
    path = simulation_state_path(settings)
    ledger_path = simulation_ledger_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    snapshot_payload = _read_state_payload(path) if path.exists() else None
    ledger_result = read_chain(ledger_path)
    if ledger_result.status == LEDGER_CORRUPTED:
        return _blocked_recovery_state(
            snapshot_payload,
            status=LEDGER_CORRUPTED,
            state_path=path,
            ledger_path=ledger_path,
            errors=list(ledger_result.errors),
        )

    checkpoint = latest_checkpoint(ledger_result.events)
    if checkpoint is not None:
        checkpoint_hash = str(ledger_result.events[-1].get("event_hash") or "")
        snapshot_hash = (
            str(snapshot_payload.get("simulation_ledger_last_hash") or "")
            if isinstance(snapshot_payload, dict)
            else ""
        )
        source_payload = snapshot_payload if snapshot_payload is not None and snapshot_hash == checkpoint_hash else checkpoint
        loaded = _state_from_payload(source_payload)
        if loaded is not None:
            loaded.simulation_session_id = str(
                first_not_none(
                    source_payload.get("simulation_session_id"),
                    ledger_result.events[-1].get("session_id"),
                    f"ui:{loaded.simulation_started_at_ms}",
                )
            )
            loaded.simulation_accounting_status = LEDGER_OK
            loaded.simulation_pnl_trusted = True
            loaded.simulation_recovery_source = (
                "STATE_SNAPSHOT" if source_payload is snapshot_payload else "LEDGER_CHECKPOINT"
            )
            loaded.simulation_ledger_last_seq = int(ledger_result.events[-1].get("event_seq") or 0)
            loaded.simulation_ledger_last_hash = checkpoint_hash
            loaded.add_event(
                "simulation_state_restored",
                (
                    "Session simulation restauree depuis le snapshot atomique."
                    if source_payload is snapshot_payload
                    else "Session simulation reconstruite depuis le ledger canonique."
                ),
                payload={
                    "state_path": str(path),
                    "ledger_path": str(ledger_path),
                    "recovery_source": loaded.simulation_recovery_source,
                },
            )
            return loaded

    if ledger_path.exists() and ledger_result.events:
        return _blocked_recovery_state(
            snapshot_payload,
            status=RECOVERY_REQUIRED,
            state_path=path,
            ledger_path=ledger_path,
            errors=[{"error": "ledger exists without a recoverable STATE_CHECKPOINT"}],
        )

    if snapshot_payload is not None:
        loaded = _state_from_payload(snapshot_payload)
        if loaded is not None:
            loaded.simulation_session_id = str(
                first_not_none(
                    snapshot_payload.get("simulation_session_id"),
                    f"ui:{loaded.simulation_started_at_ms}",
                )
            )
            loaded.simulation_recovery_source = "LEGACY_STATE_MIGRATION"
            persist_simulation_state(settings, loaded)
            return loaded

    if path.exists():
        return _blocked_recovery_state(
            None,
            status=RECOVERY_REQUIRED,
            state_path=path,
            ledger_path=ledger_path,
            errors=[{"error": "state snapshot is unreadable and no canonical ledger exists"}],
        )

    state = UiState()
    state.simulation_session_id = f"ui:{state.simulation_started_at_ms}"
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
    state.simulation_session_id = f"ui:{state.simulation_started_at_ms}"
    state.simulation_accounting_status = LEDGER_OK
    state.simulation_pnl_trusted = True
    state.simulation_recovery_source = "EXPLICIT_SESSION_RESET"
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
    ledger_path = simulation_ledger_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if state.simulation_accounting_status in {LEDGER_CORRUPTED, RECOVERY_REQUIRED}:
        raise OSError(
            f"strict persistence blocked while accounting status is {state.simulation_accounting_status}"
        )
    if not state.simulation_session_id:
        state.simulation_session_id = f"ui:{state.simulation_started_at_ms}"
    payload = _state_payload(state)
    ledger_records = _ledger_records(payload)
    sealed = write_chain_atomic(
        ledger_path,
        ledger_records,
        session_id=state.simulation_session_id,
    )
    last_row = sealed[-1]
    state.simulation_ledger_last_seq = int(last_row["event_seq"])
    state.simulation_ledger_last_hash = str(last_row["event_hash"])
    state.simulation_accounting_status = LEDGER_OK
    state.simulation_pnl_trusted = True
    payload["simulation_ledger_last_seq"] = state.simulation_ledger_last_seq
    payload["simulation_ledger_last_hash"] = state.simulation_ledger_last_hash
    payload["simulation_accounting_status"] = state.simulation_accounting_status
    payload["simulation_pnl_trusted"] = state.simulation_pnl_trusted
    _atomic_write_json(path, payload)
    return path


def _state_payload(state: UiState) -> dict:
    return {
        "version": STATE_VERSION,
        "simulation_started_at_ms": int(state.simulation_started_at_ms),
        "simulation_starting_equity_usdt": float(state.simulation_starting_equity_usdt),
        "simulation_processed_delta_keys": sorted(state.simulation_processed_delta_keys),
        "simulation_virtual_positions": _safe_position_payload(state.simulation_virtual_positions),
        "simulation_ledger_events": _safe_ledger_payload(state.simulation_ledger_events),
        "simulation_realized_pnl_usdc": float(state.simulation_realized_pnl_usdc),
        "simulation_entry_costs_paid_usdc": float(state.simulation_entry_costs_paid_usdc),
        "simulation_exit_costs_paid_usdc": float(state.simulation_exit_costs_paid_usdc),
        "simulation_reproduced_entries_total": int(state.simulation_reproduced_entries_total),
        "simulation_reproduced_exits_total": int(state.simulation_reproduced_exits_total),
        "simulation_equity_history": _safe_equity_history_payload(state.simulation_equity_history),
        "simulation_session_id": str(
            first_not_none(state.simulation_session_id, f"ui:{state.simulation_started_at_ms}")
        ),
        "simulation_accounting_status": str(state.simulation_accounting_status),
        "simulation_pnl_trusted": bool(state.simulation_pnl_trusted),
        "simulation_recovery_source": str(state.simulation_recovery_source),
        "simulation_ledger_last_seq": int(state.simulation_ledger_last_seq),
        "simulation_ledger_last_hash": str(state.simulation_ledger_last_hash),
        "updated_at_ms": now_ms(),
        "runtime_only": True,
        "notes": "Local UI simulation session state. No secrets, no orders.",
    }


def _read_state_payload(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _state_from_payload(payload: dict) -> UiState | None:
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
            for item in ledger
            if isinstance(item, dict)
        ]
    state.simulation_realized_pnl_usdc = float(
        first_not_none(_safe_float(payload.get("simulation_realized_pnl_usdc")), 0.0)
    )
    state.simulation_entry_costs_paid_usdc = float(
        first_not_none(_safe_float(payload.get("simulation_entry_costs_paid_usdc")), 0.0)
    )
    state.simulation_exit_costs_paid_usdc = float(
        first_not_none(_safe_float(payload.get("simulation_exit_costs_paid_usdc")), 0.0)
    )
    state.simulation_reproduced_entries_total = int(
        first_not_none(_safe_int(payload.get("simulation_reproduced_entries_total")), 0)
    )
    state.simulation_reproduced_exits_total = int(
        first_not_none(_safe_int(payload.get("simulation_reproduced_exits_total")), 0)
    )
    equity_history = payload.get("simulation_equity_history")
    if isinstance(equity_history, list):
        state.simulation_equity_history = [
            item
            for item in equity_history[-MAX_PERSISTED_EQUITY_POINTS:]
            if isinstance(item, dict)
        ]
    state.simulation_session_id = str(
        first_not_none(payload.get("simulation_session_id"), f"ui:{started}")
    )
    state.simulation_accounting_status = str(
        first_not_none(payload.get("simulation_accounting_status"), LEDGER_OK)
    )
    state.simulation_pnl_trusted = bool(
        first_not_none(payload.get("simulation_pnl_trusted"), True)
    )
    state.simulation_recovery_source = str(
        first_not_none(payload.get("simulation_recovery_source"), "STATE_SNAPSHOT")
    )
    state.simulation_ledger_last_seq = int(
        first_not_none(_safe_int(payload.get("simulation_ledger_last_seq")), 0)
    )
    state.simulation_ledger_last_hash = str(
        first_not_none(payload.get("simulation_ledger_last_hash"), "")
    )
    return state


def _ledger_records(payload: dict) -> list[dict]:
    session_id = str(payload["simulation_session_id"])
    records: list[dict] = [
        {
            "record_type": "SESSION_START",
            "event_id": f"{session_id}:start",
            "timestamp_ms": int(payload["simulation_started_at_ms"]),
            "starting_equity_usdt": float(payload["simulation_starting_equity_usdt"]),
        }
    ]
    for index, event in enumerate(payload.get("simulation_ledger_events") or (), start=1):
        row = {
            "record_type": "SIMULATION_EVENT",
            "simulation_event": dict(event),
        }
        causal_id = event.get("event_id") or event.get("delta_key")
        if causal_id:
            row["event_id"] = f"{session_id}:event:{causal_id}"
        else:
            row["event_id"] = f"{session_id}:event-index:{index}"
        records.append(row)
    checkpoint = dict(payload)
    checkpoint["simulation_ledger_last_seq"] = 0
    checkpoint["simulation_ledger_last_hash"] = ""
    records.append(
        {
            "record_type": "STATE_CHECKPOINT",
            "event_id": f"{session_id}:checkpoint:{payload.get('updated_at_ms')}",
            "timestamp_ms": int(payload.get("updated_at_ms") or now_ms()),
            "state": checkpoint,
        }
    )
    return records


def _blocked_recovery_state(
    snapshot_payload: dict | None,
    *,
    status: str,
    state_path: Path,
    ledger_path: Path,
    errors: list[dict],
) -> UiState:
    state = _state_from_payload(snapshot_payload) if snapshot_payload is not None else None
    if state is None:
        state = UiState()
        state.simulation_starting_equity_usdt = 0.0
        state.simulation_realized_pnl_usdc = 0.0
        state.simulation_equity_history = []
    state.simulation_accounting_status = status
    state.simulation_pnl_trusted = False
    state.simulation_recovery_source = status
    state.add_event(
        "simulation_accounting_blocked",
        "PnL strict bloque: etat/ledger non recuperable sans intervention.",
        level="ERROR",
        payload={
            "status": status,
            "state_path": str(state_path),
            "ledger_path": str(ledger_path),
            "errors": errors[:10],
        },
    )
    return state


def _atomic_write_json(path: Path, payload: dict, *, retries: int = 5) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    last_error: OSError | None = None
    for attempt in range(max(1, retries)):
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{attempt}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            return
        except OSError as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.02 * (attempt + 1))
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                    _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    if last_error is not None:
        raise last_error
    raise OSError(f"unable to persist {path}")


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
    for event in events:
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
