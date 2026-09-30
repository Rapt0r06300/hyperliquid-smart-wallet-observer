import pytest

from hl_observer.runtime_mode import (
    RuntimeMode,
    RuntimeModeDecision,
    assert_simulation_only,
    decide_runtime_mode,
)


def test_read_only_mode_remains_non_executable():
    decision = decide_runtime_mode(environment="read_only", enable_mainnet_execution=True)

    assert decision.mode == RuntimeMode.READ_ONLY
    assert decision.execution_enabled is False
    assert decision.orders_allowed is False
    assert decision.signatures_allowed is False
    assert decision.wallet_connect_allowed is False
    assert "MAINNET_EXECUTION_REFUSED" in decision.reasons
    assert_simulation_only(decision)


def test_assert_simulation_only_rejects_execution_enabled_decision():
    unsafe = RuntimeModeDecision(
        mode=RuntimeMode.PAPER,
        execution_enabled=True,
        orders_allowed=False,
        signatures_allowed=False,
        wallet_connect_allowed=False,
        reasons=("TEST_UNSAFE_SENTINEL",),
    )

    with pytest.raises(RuntimeError, match="simulation-only/read-only"):
        assert_simulation_only(unsafe)
