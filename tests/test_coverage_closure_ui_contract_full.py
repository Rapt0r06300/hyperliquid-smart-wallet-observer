from __future__ import annotations

import datetime as dt
import enum
import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect

import hl_observer.storage.models as storage_models
import hl_observer.ui.routes as ui_routes
from hl_observer.config import Settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.schemas import UiActionResult
from hl_observer.ui.state import UiState

_EXECUTION_OFF = {
    "HL_ENABLE_MAINNET_EXECUTION": "0",
    "HL_ENABLE_TESTNET_EXECUTION": "0",
    "REAL_MAINNET_TRADING": "false",
    "TESTNET_EXECUTION_ENABLED": "false",
    "HYPERSMART_ENABLE_REAL_ORDERS": "0",
    "ENABLE_REAL_ORDERS": "0",
}


def _disable_execution(monkeypatch) -> None:
    for key, value in _EXECUTION_OFF.items():
        monkeypatch.setenv(key, value)


def _path_with_safe_params(path: str) -> str:
    values = {
        "coin": "BTC",
        "symbol": "BTC",
        "wallet": "0x" + "1" * 40,
        "wallet_address": "0x" + "1" * 40,
        "address": "0x" + "1" * 40,
        "strategy": "copy",
        "family": "copy_vault",
        "run_id": "1",
        "job_id": "unit",
        "id": "1",
        "signal_id": "unit-1",
        "name": "unit",
        "file": "unit",
        "venue": "hyperliquid",
        "asset": "BTC",
    }
    return re.sub(
        r"\{([^}:]+)(?::[^}]+)?\}",
        lambda match: values.get(match.group(1), "1"),
        path,
    )


def _column_value(column, index: int):
    name = column.name.lower()
    try:
        py_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        py_type = str

    if py_type is bool:
        return True
    if py_type is int:
        return index
    if py_type is float:
        return 1.0
    if py_type is dt.datetime:
        return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    if py_type is dt.date:
        return dt.date(2026, 1, 1)
    if py_type is dict:
        return {"unit": True}
    if py_type is list:
        return ["unit"]
    if isinstance(py_type, type) and issubclass(py_type, enum.Enum):
        return list(py_type)[0]
    if py_type is str:
        if "address" in name or name in {"wallet", "wallet_address", "leader_wallet", "source_wallet"}:
            return "0x" + f"{index:x}"[-1] * 40
        if name in {"coin", "symbol", "asset"} or name.endswith("_coin"):
            return "BTC"
        if "side" in name:
            return "BUY"
        if "status" in name:
            return "ok"
        if "source" in name:
            return "unit"
        if "venue" in name:
            return "hyperliquid"
        if "action" in name:
            return "unit"
        if "decision" in name:
            return "ALLOW"
        if "reason" in name:
            return "unit"
        if "request_type" in name:
            return "l2Book"
        if "url" in name:
            return "https://example.test"
        if "path" in name or "file" in name:
            return "unit.json"
        if "hash" in name or name in {"tx", "tx_hash"}:
            return "0x" + "a" * 64
        if name == "id" or name.endswith("_id"):
            return f"unit-{index}"
        return "unit"
    return "unit"


def _representative_row(model, index: int):
    mapper = sa_inspect(model)
    values = {}
    for column in mapper.columns:
        try:
            py_type = column.type.python_type
        except (AttributeError, NotImplementedError):
            py_type = None
        if (
            column.primary_key
            and py_type is int
            and column.autoincrement in (True, "auto")
            and len(mapper.primary_key) == 1
        ):
            continue
        values[column.key] = _column_value(column, index)
    return model(**values)


def _seed_every_storage_model(settings: Settings) -> int:
    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    model_classes = sorted(
        (
            candidate
            for candidate in vars(storage_models).values()
            if isinstance(candidate, type)
            and hasattr(candidate, "__table__")
            and getattr(candidate, "__module__", "") == storage_models.__name__
        ),
        key=lambda model: model.__name__,
    )
    with session_factory() as session:
        for index, model in enumerate(model_classes, start=1):
            session.add(_representative_row(model, index))
            session.flush()
        session.commit()
    return len(model_classes)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'ui-contract.sqlite3'}",
        logs_dir=str(tmp_path / "logs"),
    )


def test_every_get_route_serializes_representative_persisted_state(tmp_path, monkeypatch) -> None:
    _disable_execution(monkeypatch)
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    seeded = _seed_every_storage_model(settings)
    assert seeded >= 60

    app = create_ui_app(settings, UiState())
    client = TestClient(app, raise_server_exceptions=False)
    observed = []
    for route in app.routes:
        if "GET" not in set(getattr(route, "methods", []) or []):
            continue
        path = _path_with_safe_params(route.path)
        response = client.get(
            path,
            params={
                "limit": 2,
                "max_leaders": 2,
                "fresh_window_seconds": 999_999_999,
                "window": 1,
                "coin": "BTC",
            },
        )
        observed.append((path, response.status_code))
        assert response.status_code < 500, (path, response.status_code, response.text[:500])

    assert len(observed) >= 70
    assert any(path == "/api/status" and code == 200 for path, code in observed)
    assert any(path == "/api/simulation/status" and code == 200 for path, code in observed)


def test_every_post_route_stays_offline_and_action_dispatch_is_safe(tmp_path, monkeypatch) -> None:
    _disable_execution(monkeypatch)
    monkeypatch.chdir(tmp_path)

    async def fake_run(action, settings, state):
        del settings, state
        return UiActionResult(
            action=action,
            action_id=action,
            label=action,
            allowed=True,
            success=True,
            message="ok",
            status="success",
            level="INFO",
            details={"unit": True},
            started_at_ms=1,
            finished_at_ms=2,
            affected_counts={},
        )

    monkeypatch.setattr(ui_routes, "run_safe_action", fake_run)

    app = create_ui_app(_settings(tmp_path), UiState())
    client = TestClient(app, raise_server_exceptions=False)
    post_routes = [route.path for route in app.routes if "POST" in set(getattr(route, "methods", []) or [])]
    assert post_routes

    for path in post_routes:
        if path == "/api/actions":
            for action in ("reset_simulation_session", "doctor", "activate_kill_switch", "unknown_action"):
                response = client.post(path, json={"action": action})
                assert response.status_code == 200, (path, action, response.text[:500])
        else:
            response = client.post(path, json={})
            assert response.status_code == 200, (path, response.text[:500])
