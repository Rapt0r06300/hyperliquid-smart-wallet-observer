from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hl_observer.core.circuit_breaker import CircuitBreaker
from hl_observer.core.config import CoreConfig, default_core_config
from hl_observer.core.error_handler import ErrorHandler
from hl_observer.core.retry import RetryPolicy
from hl_observer.core.state_manager import StateManager


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    config: CoreConfig
    errors: ErrorHandler
    retry_policy: RetryPolicy
    circuit_breaker: CircuitBreaker
    state_manager: StateManager


def build_core_runtime(project_root: str | Path = ".") -> CoreRuntime:
    cfg = default_core_config(project_root)
    return CoreRuntime(
        config=cfg,
        errors=ErrorHandler(cfg.logs_dir / "hypersmart_core_errors.jsonl"),
        retry_policy=RetryPolicy(
            max_attempts=cfg.max_retry_attempts,
            base_delay_seconds=cfg.retry_base_delay_seconds,
        ),
        circuit_breaker=CircuitBreaker(
            "hyperliquid_readonly",
            failure_threshold=cfg.circuit_failure_threshold,
            recovery_timeout_seconds=cfg.circuit_recovery_timeout_seconds,
        ),
        state_manager=StateManager(cfg.runtime_dir / "state" / "core_runtime.json"),
    )


__all__ = ["CoreRuntime", "build_core_runtime"]
