import pytest

from hl_observer.config.defaults import safe_defaults_from_env
from hl_observer.runtime_mode import RuntimeMode, assert_simulation_only, decide_runtime_mode
from hl_observer.storage.run_context import (
    RunContext,
    assert_same_run_context,
    build_run_context_scope,
    may_merge_pnl,
)


def test_runtime_mode_defaults_to_paper_without_execution():
    decision = decide_runtime_mode(environment="paper")

    assert decision.mode == RuntimeMode.PAPER
    assert decision.execution_enabled is False
    assert decision.orders_allowed is False
    assert decision.signatures_allowed is False
    assert decision.wallet_connect_allowed is False
    assert "NO_REAL_ORDERS" in decision.reasons
    assert_simulation_only(decision)


def test_testnet_mode_is_locked_not_executable():
    decision = decide_runtime_mode(environment="testnet", enable_testnet_execution=True)

    assert decision.mode == RuntimeMode.TESTNET_LOCKED
    assert decision.execution_enabled is False
    assert "TESTNET_EXECUTION_LOCKED" in decision.reasons
    assert_simulation_only(decision)


def test_safe_defaults_are_deny_by_default(monkeypatch):
    for name in [
        "HL_NETWORK_READ_DEFAULT",
        "HL_ENABLE_MAINNET_EXECUTION",
        "HL_ENABLE_TESTNET_EXECUTION",
        "HL_ALLOW_FAKE_DATA",
        "HL_ALLOW_FAKE_PNL",
    ]:
        monkeypatch.delenv(name, raising=False)

    defaults = safe_defaults_from_env()

    assert defaults.deny_by_default is True
    assert defaults.dry_run_default is True
    assert defaults.network_read_default is False
    assert defaults.max_api_errors == 5


def test_safe_defaults_surface_unsafe_env_for_audit(monkeypatch):
    monkeypatch.setenv("HL_ALLOW_FAKE_PNL", "true")

    defaults = safe_defaults_from_env()

    assert defaults.fake_pnl_allowed is True
    assert defaults.deny_by_default is False


def test_run_context_scope_prevents_live_backtest_pnl_mix():
    live = build_run_context_scope(RunContext.LIVE, run_id="session-a")
    backtest = build_run_context_scope(RunContext.BACKTEST, run_id="session-a")

    assert live.pnl_namespace == "LIVE:session-a"
    assert may_merge_pnl(live, backtest) is False
    with pytest.raises(ValueError, match="run context mismatch"):
        assert_same_run_context(live, backtest)


def test_run_context_scope_prevents_session_mix_inside_same_context():
    left = build_run_context_scope("REPLAY", run_id="run-1", paper_session_id="paper-1")
    right = build_run_context_scope("REPLAY", run_id="run-2", paper_session_id="paper-2")

    assert may_merge_pnl(left, right) is False
    with pytest.raises(ValueError, match="paper session mismatch"):
        assert_same_run_context(left, right)


def test_run_context_scope_allows_same_context_and_session():
    left = build_run_context_scope("TEST_FIXTURE", run_id="fixture", paper_session_id="shared")
    right = build_run_context_scope("TEST_FIXTURE", run_id="fixture-2", paper_session_id="shared")

    assert may_merge_pnl(left, right) is True
    assert_same_run_context(left, right)
