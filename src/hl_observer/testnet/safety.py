from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.models import TestnetOrderRequest, TestnetPositionSnapshot

TESTNET_DISABLED_REASON = "TESTNET_DISABLED_BY_REPOSITORY_POLICY"


@dataclass(frozen=True, slots=True)
class TestnetGuardDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


class TestnetSafetyGuard:
    """Permanent fail-closed gate: this repository does not permit testnet actions."""

    def evaluate(
        self,
        settings: Settings,
        adapter: TestnetExchangeAdapter,
        request: TestnetOrderRequest,
        *,
        confirmed: bool,
        open_positions: list[TestnetPositionSnapshot],
    ) -> TestnetGuardDecision:
        # Testnet is outside the supported PAPER/READ-ONLY runtime scope. Keep this
        # unconditional: configuration, environment variables and CLI confirmations
        # must never turn this adapter path into an order-submission capability.
        return TestnetGuardDecision(
            allowed=False,
            reasons=[TESTNET_DISABLED_REASON],
        )


def build_testnet_runtime_settings(settings: Settings, *, confirmed: bool, max_notional: float | None = None) -> Settings:
    """Return a PAPER-only copy; legacy testnet CLI flags cannot enable execution."""
    del confirmed, max_notional
    updated = settings.model_copy(deep=True)
    updated.environment = ExecutionEnvironment.PAPER
    updated.execution.enable_mainnet_execution = False
    updated.execution.real_mainnet_trading = False
    updated.execution.allow_mainnet_order_submission = False
    updated.execution.testnet_only = True
    updated.execution.testnet_mode = False
    updated.execution.enable_testnet_execution = False
    updated.execution.testnet_execution_enabled = False
    updated.execution.confirm_testnet_execution = False
    updated.execution.require_explicit_testnet_confirmation = True
    return updated
