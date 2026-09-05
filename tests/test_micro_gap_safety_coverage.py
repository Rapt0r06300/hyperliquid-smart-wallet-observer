from types import SimpleNamespace

import pytest

from hl_observer.config.settings import ExecutionEnvironment
from hl_observer.execution_core.central_budget_checker import BudgetCentral
from hl_observer.hyperliquid.schemas import SignalDecision
from hl_observer.order_lifecycle.post_only_invariant import REJETE, verifier
from hl_observer.security.mainnet_guard import MainnetExecutionForbidden, assert_not_mainnet_execution
import hl_observer.testnet.testnet_executor_locked as locked_executor


def test_mainnet_guard_rejects_mainnet_environment_even_with_execution_flag_off() -> None:
    settings = SimpleNamespace(
        execution=SimpleNamespace(enable_mainnet_execution=False),
        environment=ExecutionEnvironment.MAINNET,
    )
    with pytest.raises(MainnetExecutionForbidden, match="HL_ENV=mainnet") as exc_info:
        assert_not_mainnet_execution(settings)
    assert exc_info.value.decision is SignalDecision.REJECT_MAINNET_FORBIDDEN


def test_central_budget_rejects_duplicate_reservation_without_mutating_budget() -> None:
    budget = BudgetCentral(100.0)
    assert budget.reserver("copy-vault", 25.0)["ok"] is True
    duplicate = budget.reserver("copy-vault", 10.0)
    assert duplicate == {"ok": False, "raison": "ID_DEJA_RESERVE", "disponible": 75.0}
    assert budget.disponible() == 75.0


def test_post_only_unknown_side_fails_closed() -> None:
    assert verifier(100.0, 101.0, "UNKNOWN") == {"decision": REJETE, "raison": "SENS_INCONNU"}


def test_locked_testnet_executor_returns_only_validated_scaffold_after_gate(monkeypatch) -> None:
    observed = {}

    def fake_gate(settings, risk_decision, intent):
        observed["settings"] = settings
        observed["risk_decision"] = risk_decision
        observed["intent"] = intent

    monkeypatch.setattr(locked_executor, "assert_testnet_unlocked", fake_gate)
    settings = SimpleNamespace(execution=SimpleNamespace(require_schedule_cancel=True))
    order = SimpleNamespace(cloid="paper-cloid", schedule_cancel_configured=True, reduce_only=True)
    risk_decision = object()

    result = locked_executor.LockedTestnetExecutor(settings).submit(
        order,
        risk_decision,
        confirm_testnet_only=True,
    )

    assert result == {"status": "validated_testnet_only", "cloid": "paper-cloid"}
    assert observed["settings"] is settings
    assert observed["risk_decision"] is risk_decision
    assert observed["intent"].confirm_testnet_only is True
    assert observed["intent"].schedule_cancel_required is True
    assert observed["intent"].schedule_cancel_configured is True
    assert observed["intent"].reduce_only is True
