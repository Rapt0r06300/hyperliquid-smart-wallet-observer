from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class RuntimeMode(StrEnum):
    """Runtime posture for HyperSmart.

    PAPER is the normal live simulation mode. It observes real Hyperliquid
    market data, but it never sends orders, signs payloads, or connects a wallet.
    """

    PAPER = "PAPER"
    READ_ONLY = "READ_ONLY"
    TESTNET_LOCKED = "TESTNET_LOCKED"


@dataclass(frozen=True, slots=True)
class RuntimeModeDecision:
    mode: RuntimeMode
    execution_enabled: bool
    orders_allowed: bool
    signatures_allowed: bool
    wallet_connect_allowed: bool
    reasons: tuple[str, ...]


def decide_runtime_mode(
    *,
    environment: str = "paper",
    enable_mainnet_execution: bool = False,
    enable_testnet_execution: bool = False,
) -> RuntimeModeDecision:
    """Resolve safe runtime mode from settings-like primitives."""

    normalized_env = str(environment or "paper").strip().lower()
    reasons: list[str] = ["HYPERLIQUID_ONLY", "SIMULATION_LOCAL_ONLY", "NO_REAL_ORDERS"]
    if enable_mainnet_execution:
        reasons.append("MAINNET_EXECUTION_REFUSED")
    if enable_testnet_execution:
        reasons.append("TESTNET_EXECUTION_LOCKED")
    if normalized_env == "read_only":
        mode = RuntimeMode.READ_ONLY
    elif normalized_env == "testnet" or enable_testnet_execution:
        mode = RuntimeMode.TESTNET_LOCKED
    else:
        mode = RuntimeMode.PAPER
    return RuntimeModeDecision(
        mode=mode,
        execution_enabled=False,
        orders_allowed=False,
        signatures_allowed=False,
        wallet_connect_allowed=False,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def assert_simulation_only(decision: RuntimeModeDecision) -> None:
    if decision.execution_enabled or decision.orders_allowed or decision.signatures_allowed:
        raise RuntimeError("HyperSmart runtime must remain simulation-only/read-only.")
