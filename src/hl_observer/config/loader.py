from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from hl_observer.config.settings import (
    ExecutionEnvironment,
    ExecutionSettings,
    HyperliquidSettings,
    RiskSettings,
    Settings,
)


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


def load_settings(config_path: str | Path | None = None) -> Settings:
    raw = _load_yaml(Path(config_path) if config_path else Path("config/settings.example.yaml"))
    app_raw = raw.get("app", {}) if isinstance(raw.get("app", {}), dict) else {}
    hl_raw = raw.get("hyperliquid", {}) if isinstance(raw.get("hyperliquid", {}), dict) else {}
    exec_raw = raw.get("execution", {}) if isinstance(raw.get("execution", {}), dict) else {}

    environment = os.getenv("HL_ENV", app_raw.get("environment", "paper"))
    database_url = os.getenv("HL_DATABASE_URL", app_raw.get("database_url", Settings().database_url))
    logs_dir = Path(os.getenv("HL_LOGS_DIR", app_raw.get("logs_dir", "./logs")))

    execution = ExecutionSettings(
        enable_mainnet_execution=_as_bool(
            os.getenv("HL_ENABLE_MAINNET_EXECUTION"),
            bool(exec_raw.get("enable_mainnet_execution", False)),
        ),
        enable_testnet_execution=_as_bool(
            os.getenv("HL_ENABLE_TESTNET_EXECUTION"),
            bool(exec_raw.get("enable_testnet_execution", False)),
        ),
        require_confirm_testnet_only=bool(exec_raw.get("require_confirm_testnet_only", True)),
        require_cloid=bool(exec_raw.get("require_cloid", True)),
        require_schedule_cancel=_as_bool(
            os.getenv("HL_REQUIRE_TESTNET_SCHEDULE_CANCEL"),
            bool(exec_raw.get("require_schedule_cancel", True)),
        ),
        require_reduce_only_exits=bool(exec_raw.get("require_reduce_only_exits", True)),
    )

    return Settings(
        environment=ExecutionEnvironment(str(environment)),
        database_url=str(database_url),
        logs_dir=logs_dir,
        log_level=os.getenv("HL_LOG_LEVEL", "INFO"),
        hyperliquid=HyperliquidSettings(**hl_raw),
        execution=execution,
        risk=RiskSettings(),
    )
