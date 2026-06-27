from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SafeRuntimeDefaults:
    network_read_default: bool = False
    dry_run_default: bool = True
    max_api_errors: int = 5
    retry_count: int = 2
    retry_backoff_seconds: float = 1.0
    mainnet_execution_enabled: bool = False
    testnet_execution_enabled: bool = False
    fake_data_allowed: bool = False
    fake_pnl_allowed: bool = False

    @property
    def deny_by_default(self) -> bool:
        return (
            not self.network_read_default
            and self.dry_run_default
            and not self.mainnet_execution_enabled
            and not self.testnet_execution_enabled
            and not self.fake_data_allowed
            and not self.fake_pnl_allowed
        )


def safe_defaults_from_env(prefix: str = "HL") -> SafeRuntimeDefaults:
    return SafeRuntimeDefaults(
        network_read_default=_env_bool(f"{prefix}_NETWORK_READ_DEFAULT", False),
        dry_run_default=_env_bool(f"{prefix}_DRY_RUN_DEFAULT", True),
        max_api_errors=max(1, _env_int(f"{prefix}_MAX_API_ERRORS", 5)),
        retry_count=max(0, _env_int(f"{prefix}_RETRY_COUNT", 2)),
        retry_backoff_seconds=max(0.0, _env_float(f"{prefix}_RETRY_BACKOFF_SECONDS", 1.0)),
        mainnet_execution_enabled=_env_bool(f"{prefix}_ENABLE_MAINNET_EXECUTION", False),
        testnet_execution_enabled=_env_bool(f"{prefix}_ENABLE_TESTNET_EXECUTION", False),
        fake_data_allowed=_env_bool(f"{prefix}_ALLOW_FAKE_DATA", False),
        fake_pnl_allowed=_env_bool(f"{prefix}_ALLOW_FAKE_PNL", False),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default
