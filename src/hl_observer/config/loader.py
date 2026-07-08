from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from hl_observer.config.settings import (
    CollectionSettings,
    CopyTradingSettings,
    AdaptiveRiskFilterSettings,
    ExecutionEnvironment,
    ExecutionSettings,
    HyperliquidSettings,
    MarketUniverseSettings,
    RiskSettings,
    Settings,
    WalletBootstrapSettings,
    WalletAnalysisSettings,
    WalletDiscoverySettings,
    WalletScannerSettings,
)


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | float | int | None, default: float) -> float:
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: str | int | None, default: int) -> int:
    if value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


def load_settings(config_path: str | Path | None = None) -> Settings:
    if config_path:
        path = Path(config_path)
    else:
        custom_path = Path("config/settings.yaml")
        path = custom_path if custom_path.exists() else Path("config/settings.example.yaml")
    raw = _load_yaml(path)
    app_raw = raw.get("app", {}) if isinstance(raw.get("app", {}), dict) else {}
    hl_raw = raw.get("hyperliquid", {}) if isinstance(raw.get("hyperliquid", {}), dict) else {}
    collection_raw = raw.get("collection", {}) if isinstance(raw.get("collection", {}), dict) else {}
    discovery_raw = raw.get("wallet_discovery", {}) if isinstance(raw.get("wallet_discovery", {}), dict) else {}
    bootstrap_raw = raw.get("wallet_bootstrap", {}) if isinstance(raw.get("wallet_bootstrap", {}), dict) else {}
    scanner_raw = raw.get("wallet_scanner", {}) if isinstance(raw.get("wallet_scanner", {}), dict) else {}
    market_universe_raw = raw.get("market_universe", {}) if isinstance(raw.get("market_universe", {}), dict) else {}
    wallet_analysis_raw = raw.get("wallet_analysis", {}) if isinstance(raw.get("wallet_analysis", {}), dict) else {}
    adaptive_risk_raw = raw.get("adaptive_risk_filter", {}) if isinstance(raw.get("adaptive_risk_filter", {}), dict) else {}
    copy_raw = raw.get("copy_trading", {}) if isinstance(raw.get("copy_trading", {}), dict) else {}
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
            os.getenv("HL_ENABLE_TESTNET_EXECUTION", os.getenv("TESTNET_EXECUTION_ENABLED")),
            bool(exec_raw.get("enable_testnet_execution", False)),
        ),
        real_mainnet_trading=_as_bool(
            os.getenv("REAL_MAINNET_TRADING"),
            bool(exec_raw.get("real_mainnet_trading", False)),
        ),
        testnet_only=_as_bool(
            os.getenv("TESTNET_ONLY"),
            bool(exec_raw.get("testnet_only", True)),
        ),
        testnet_mode=_as_bool(
            os.getenv("TESTNET_MODE"),
            bool(exec_raw.get("testnet_mode", False)),
        ),
        testnet_execution_enabled=_as_bool(
            os.getenv("TESTNET_EXECUTION_ENABLED"),
            bool(exec_raw.get("testnet_execution_enabled", False)),
        ),
        confirm_testnet_execution=_as_bool(
            os.getenv("CONFIRM_TESTNET_EXECUTION"),
            bool(exec_raw.get("confirm_testnet_execution", False)),
        ),
        require_explicit_testnet_confirmation=_as_bool(
            os.getenv("REQUIRE_EXPLICIT_TESTNET_CONFIRMATION"),
            bool(exec_raw.get("require_explicit_testnet_confirmation", True)),
        ),
        testnet_exchange=os.getenv("TESTNET_EXCHANGE", str(exec_raw.get("testnet_exchange", "hyperliquid"))),
        max_testnet_notional=_as_float(
            os.getenv("MAX_TESTNET_NOTIONAL"),
            float(exec_raw.get("max_testnet_notional", 5.0)),
        ),
        max_open_testnet_positions=_as_int(
            os.getenv("MAX_OPEN_TESTNET_POSITIONS"),
            int(exec_raw.get("max_open_testnet_positions", 1)),
        ),
        allow_mainnet_order_submission=_as_bool(
            os.getenv("ALLOW_MAINNET_ORDER_SUBMISSION"),
            bool(exec_raw.get("allow_mainnet_order_submission", False)),
        ),
        testnet_adapter=os.getenv("TESTNET_ADAPTER", str(exec_raw.get("testnet_adapter", "fake"))),
        require_confirm_testnet_only=bool(exec_raw.get("require_confirm_testnet_only", True)),
        require_cloid=bool(exec_raw.get("require_cloid", True)),
        require_schedule_cancel=_as_bool(
            os.getenv("HL_REQUIRE_TESTNET_SCHEDULE_CANCEL"),
            bool(exec_raw.get("require_schedule_cancel", True)),
        ),
        require_reduce_only_exits=bool(exec_raw.get("require_reduce_only_exits", True)),
    )

    # ANTI-BLOAT (crash observe: DB 29 Go -> corrompue). Un run long dumpait les
    # payloads bruts (L2 books, leaderboards, fills) sans cap. HYPERSMART_DISABLE_RAW_STORAGE=1
    # coupe les 3 stockages bruts d'un coup (le ledger canonique n'en depend pas).
    if _as_bool(os.getenv("HYPERSMART_DISABLE_RAW_STORAGE"), False):
        collection_raw["store_raw_events"] = False
        discovery_raw["store_raw_discovery_payloads"] = False
        bootstrap_raw["store_raw_source_payloads"] = False

    return Settings(
        environment=ExecutionEnvironment(str(environment)),
        database_url=str(database_url),
        logs_dir=logs_dir,
        log_level=os.getenv("HL_LOG_LEVEL", "INFO"),
        hyperliquid=HyperliquidSettings(**hl_raw),
        collection=CollectionSettings(**collection_raw),
        wallet_discovery=WalletDiscoverySettings(**discovery_raw),
        wallet_bootstrap=WalletBootstrapSettings(**bootstrap_raw),
        wallet_scanner=WalletScannerSettings(**scanner_raw),
        market_universe=MarketUniverseSettings(**market_universe_raw),
        wallet_analysis=WalletAnalysisSettings(**wallet_analysis_raw),
        adaptive_risk_filter=AdaptiveRiskFilterSettings(**adaptive_risk_raw),
        execution=execution,
        risk=RiskSettings(),
        copy_trading=CopyTradingSettings(**copy_raw),
    )
