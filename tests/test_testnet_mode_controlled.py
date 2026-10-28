from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.testnet.adapters import FakeTestnetExchangeAdapter, HyperliquidTestnetAdapter
from hl_observer.testnet.commands import build_testnet_status
from hl_observer.testnet.dashboard_payload import build_testnet_dashboard_payload
from hl_observer.testnet.executor import TestnetExecutor as Executor
from hl_observer.testnet.journal import TestnetDecisionJournal as DecisionJournal
from hl_observer.testnet.models import TestnetAction as Action
from hl_observer.testnet.models import TestnetOrderRequest as OrderRequest
from hl_observer.testnet.models import TestnetSide as Side
from hl_observer.testnet.safety import TestnetSafetyGuard, build_testnet_runtime_settings


def _testnet_settings(*, confirmed: bool = True) -> Settings:
    settings = build_testnet_runtime_settings(Settings(), confirmed=confirmed)
    settings.execution.max_testnet_notional = 50.0
    settings.execution.max_open_testnet_positions = 2
    return settings


def _request(*, notional: float = 10.0) -> OrderRequest:
    return OrderRequest(
        cloid="unit-test-cloid",
        action=Action.OPEN,
        coin="BTC",
        side=Side.LONG,
        notional_usdc=notional,
        limit_price=100.0,
        evidence={"test": "controlled_testnet"},
    )


def test_legacy_runtime_settings_helper_cannot_arm_testnet_flags():
    settings = Settings()
    settings.environment = ExecutionEnvironment.TESTNET
    settings.execution.enable_testnet_execution = True
    settings.execution.testnet_execution_enabled = True

    paper_settings = build_testnet_runtime_settings(settings, confirmed=True, max_notional=100.0)

    assert paper_settings.environment is ExecutionEnvironment.PAPER
    assert paper_settings.execution.enable_mainnet_execution is False
    assert paper_settings.execution.enable_testnet_execution is False
    assert paper_settings.execution.testnet_execution_enabled is False
    assert paper_settings.execution.confirm_testnet_execution is False
    assert settings.execution.enable_testnet_execution is True


def test_executor_refuses_every_testnet_path_without_reading_or_mutating_adapter(tmp_path, monkeypatch):
    settings = _testnet_settings(confirmed=True)
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    journal = DecisionJournal(tmp_path / "testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    def forbidden_adapter_read(_self):
        raise AssertionError("disabled testnet path must not query the adapter")

    monkeypatch.setattr(FakeTestnetExchangeAdapter, "get_testnet_positions", forbidden_adapter_read)
    opened = executor.open_position(_request(), confirmed=True)
    closed = executor.close_position("BTC", Side.LONG, cloid="close-btc", confirmed=True)

    for result in (opened, closed):
        assert not result.accepted
        assert result.reasons == ["TESTNET_DISABLED_BY_REPOSITORY_POLICY"]
        assert result.realized_pnl_usdc is None
        assert result.unrealized_pnl_usdc is None
    assert adapter.orders == []
    journal_text = journal.path.read_text(encoding="utf-8")
    assert journal_text.count("REJECT_TESTNET_GUARD") == 2
    assert "testnet_order_result" not in journal_text
    with pytest.raises(RuntimeError, match="TESTNET_DISABLED_BY_REPOSITORY_POLICY"):
        executor.get_portfolio()
    with pytest.raises(RuntimeError, match="TESTNET_DISABLED_BY_REPOSITORY_POLICY"):
        executor.apply_exit_plan(confirmed=True, mark_prices={"BTC": 110.0})
    with pytest.raises(TypeError):
        Executor(settings=settings, adapter=adapter, journal=journal, guard=object())


def test_guard_refuses_without_confirmation_and_journals(tmp_path):
    settings = _testnet_settings(confirmed=False)
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    journal = DecisionJournal(tmp_path / "testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    result = executor.open_position(_request(), confirmed=False)

    assert not result.accepted
    assert result.reasons == ["TESTNET_DISABLED_BY_REPOSITORY_POLICY"]
    assert "REJECT_TESTNET_GUARD" in journal.path.read_text(encoding="utf-8")


def test_guard_refuses_if_testnet_execution_disabled():
    settings = Settings()
    settings.environment = ExecutionEnvironment.TESTNET
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})

    decision = TestnetSafetyGuard().evaluate(
        settings,
        adapter,
        _request(),
        confirmed=True,
        open_positions=[],
    )

    assert not decision.allowed
    assert decision.reasons == ["TESTNET_DISABLED_BY_REPOSITORY_POLICY"]


def test_guard_refuses_mainnet_like_url():
    settings = _testnet_settings()
    adapter = HyperliquidTestnetAdapter(base_url="https://api.hyperliquid.xyz")

    decision = TestnetSafetyGuard().evaluate(
        settings,
        adapter,
        _request(),
        confirmed=True,
        open_positions=[],
    )

    assert not decision.allowed
    assert decision.reasons == ["TESTNET_DISABLED_BY_REPOSITORY_POLICY"]


def test_hyperliquid_testnet_adapter_is_ready_but_locked_until_signature_transport():
    settings = _testnet_settings()
    adapter = HyperliquidTestnetAdapter()
    journal = DecisionJournal(settings.logs_dir / "logs à envoyer" / "test-hl-testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    result = executor.open_position(_request(), confirmed=True)

    assert not result.accepted
    assert result.reasons == ["TESTNET_DISABLED_BY_REPOSITORY_POLICY"]
    assert adapter.connected is False


def test_dashboard_payload_hides_positions_and_pnl_when_testnet_is_disabled():
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    payload = build_testnet_dashboard_payload(adapter)

    assert payload["mode"] == "DISABLED_BY_SCOPE"
    assert payload["environment"] == "paper"
    assert payload["orders_enabled"] is False
    assert payload["open_positions"] is None
    assert payload["pnl_status"] == "UNMEASURABLE"


def test_cli_legacy_testnet_run_is_refused_without_initializing_adapter(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "testnet-run",
            "--dry-confirmed",
            "--confirm-testnet",
            "--exchange",
            "fake",
            "--coin",
            "BTC",
            "--side",
            "long",
            "--notional",
            "1",
            "--limit-price",
            "100",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "rejected"
    assert payload["adapter"] == "disabled_by_scope"
    assert payload["payload"]["mode"] == "DISABLED_BY_SCOPE"
    assert payload["payload"]["orders_created"] == 0
    assert payload["payload"]["pnl_status"] == "UNMEASURABLE"


def test_testnet_status_does_not_create_a_fake_portfolio():
    payload = build_testnet_status(Settings(), adapter_name="fake")

    assert payload == {
        "mode": "DISABLED_BY_SCOPE",
        "environment": "paper",
        "adapter": "not initialized",
        "orders_enabled": False,
        "pnl_status": "UNMEASURABLE",
        "reason": "TESTNET_DISABLED_BY_REPOSITORY_POLICY",
    }


def test_testnet_loop_option_refuses_before_network_observation():
    result = CliRunner().invoke(app, ["testnet-loop-observe", "--execute-fake-testnet"])

    assert result.exit_code == 2
    assert "Testnet disabled by repository policy" in result.output
