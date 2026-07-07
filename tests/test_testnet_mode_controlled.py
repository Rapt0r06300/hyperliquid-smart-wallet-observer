from __future__ import annotations

import json

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.testnet.adapters import FakeTestnetExchangeAdapter, HyperliquidTestnetAdapter
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


def test_fake_adapter_opens_closes_and_reports_testnet_pnl(tmp_path):
    settings = _testnet_settings()
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    journal = DecisionJournal(tmp_path / "testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    opened = executor.open_position(_request(), confirmed=True)
    assert opened.accepted
    assert adapter.get_testnet_positions()[0].notional_usdc == 10.0

    adapter.prices["BTC"] = 110.0
    closed = executor.close_position("BTC", Side.LONG, cloid="close-btc", confirmed=True)
    assert closed.accepted
    assert closed.realized_pnl_usdc == 1.0

    portfolio = executor.get_portfolio()
    assert portfolio.realized_pnl_usdc == 1.0
    assert portfolio.equity_usdc == 1001.0
    assert journal.path.read_text(encoding="utf-8").count("testnet_order_result") == 2


def test_guard_refuses_without_confirmation_and_journals(tmp_path):
    settings = _testnet_settings(confirmed=False)
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    journal = DecisionJournal(tmp_path / "testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    result = executor.open_position(_request(), confirmed=False)

    assert not result.accepted
    assert "--confirm-testnet is required" in result.reasons
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
    assert "TESTNET_EXECUTION_ENABLED must be true" in decision.reasons


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
    assert "adapter URL must be testnet" in decision.reasons


def test_hyperliquid_testnet_adapter_is_ready_but_locked_until_signature_transport():
    settings = _testnet_settings()
    adapter = HyperliquidTestnetAdapter()
    journal = DecisionJournal(settings.logs_dir / "logs à envoyer" / "test-hl-testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)

    result = executor.open_position(_request(), confirmed=True)

    assert not result.accepted
    assert result.reasons == ["READY_BUT_LOCKED_SIGNATURE_REQUIRED"]
    assert adapter.environment == "testnet"
    assert "testnet" in adapter.base_url


def test_dashboard_payload_exposes_testnet_positions_and_pnl(tmp_path):
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 100.0})
    settings = _testnet_settings()
    journal = DecisionJournal(tmp_path / "testnet.jsonl")
    executor = Executor(settings=settings, adapter=adapter, journal=journal)
    executor.open_position(_request(), confirmed=True)

    payload = build_testnet_dashboard_payload(adapter, journal_path=journal.path)

    assert payload["mode"] == "TESTNET_ONLY"
    assert payload["environment"] == "testnet"
    assert payload["open_positions"]
    assert payload["journal_tail"]


def test_cli_testnet_run_dry_confirmed_uses_fake_adapter(monkeypatch, tmp_path):
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
    assert payload["status"] == "accepted"
    assert payload["adapter"] == "fake_hyperliquid_testnet"
    assert payload["payload"]["mode"] == "TESTNET_ONLY"
