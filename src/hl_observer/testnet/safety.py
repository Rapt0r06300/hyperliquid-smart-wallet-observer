from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.models import TestnetOrderRequest, TestnetPositionSnapshot


@dataclass(frozen=True, slots=True)
class TestnetGuardDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


class TestnetSafetyGuard:
    """Central fail-closed gate for every external testnet action."""

    def evaluate(
        self,
        settings: Settings,
        adapter: TestnetExchangeAdapter,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
        open_positions: list[TestnetPositionSnapshot],
    ) -> TestnetGuardDecision:
        reasons: list[str] = []
        execution = settings.execution
        base_url = getattr(adapter, "base_url", "")
        environment = getattr(adapter, "environment", "")

        if settings.environment != ExecutionEnvironment.TESTNET:
            reasons.append("HL_ENV must be testnet")
        if execution.real_mainnet_trading:
            reasons.append("REAL_MAINNET_TRADING must be false")
        if execution.enable_mainnet_execution or execution.allow_mainnet_order_submission:
            reasons.append("mainnet order submission flags must remain false")
        if not execution.testnet_only:
            reasons.append("TESTNET_ONLY must be true")
        if not execution.testnet_mode:
            reasons.append("TESTNET_MODE must be true")
        if not execution.enable_testnet_execution or not execution.testnet_execution_enabled:
            reasons.append("TESTNET_EXECUTION_ENABLED must be true")
        if execution.require_explicit_testnet_confirmation and not confirmed:
            reasons.append("--confirm-testnet is required")
        if execution.confirm_testnet_execution is not True:
            reasons.append("CONFIRM_TESTNET_EXECUTION must be true")
        if environment != "testnet":
            reasons.append("adapter environment must be testnet")
        if "testnet" not in base_url.lower():
            reasons.append("adapter URL must be testnet")
        if request.notional_usdc > execution.max_testnet_notional:
            reasons.append("testnet notional exceeds MAX_TESTNET_NOTIONAL")
        if len(open_positions) >= execution.max_open_testnet_positions and request.action.value == "open":
            reasons.append("too many open testnet positions")

        return TestnetGuardDecision(allowed=not reasons, reasons=reasons)


def build_testnet_runtime_settings(settings: Settings, *, confirmed: bool, max_notional: float | None = None) -> Settings:
    """Return a copy configured for explicit local testnet runs.

    The function is used by CLI dry-confirmed mode so tests can exercise the chain
    without requiring a persistent environment mutation.
    """

    updated = settings.model_copy(deep=True)
    updated.environment = ExecutionEnvironment.TESTNET
    updated.execution.real_mainnet_trading = False
    updated.execution.testnet_only = True
    updated.execution.testnet_mode = True
    updated.execution.enable_testnet_execution = True
    updated.execution.testnet_execution_enabled = True
    updated.execution.confirm_testnet_execution = bool(confirmed)
    updated.execution.require_explicit_testnet_confirmation = True
    updated.execution.allow_mainnet_order_submission = False
    if max_notional is not None:
        updated.execution.max_testnet_notional = float(max_notional)
    return updated
