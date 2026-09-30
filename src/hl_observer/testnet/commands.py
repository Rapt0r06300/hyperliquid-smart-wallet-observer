from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hl_observer.config.settings import Settings
from hl_observer.testnet.adapters import FakeTestnetExchangeAdapter, HyperliquidTestnetAdapter, TestnetExchangeAdapter
from hl_observer.testnet.dashboard_payload import build_testnet_dashboard_payload
from hl_observer.testnet.executor import TestnetExecutor
from hl_observer.testnet.journal import TestnetDecisionJournal, default_testnet_journal_path
from hl_observer.testnet.models import TestnetAction, TestnetOrderRequest, TestnetSide
from hl_observer.testnet.safety import build_testnet_runtime_settings


@dataclass(frozen=True, slots=True)
class TestnetRunCommandResult:
    status: str
    adapter: str
    action: str
    payload: dict[str, object]
    journal_path: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "adapter": self.adapter,
                "action": self.action,
                "payload": self.payload,
                "journal_path": self.journal_path,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def build_testnet_adapter(name: str, *, price: float, coin: str) -> TestnetExchangeAdapter:
    normalized = name.strip().lower()
    if normalized in {"fake", "fake_hyperliquid", "fake_hyperliquid_testnet"}:
        return FakeTestnetExchangeAdapter(prices={coin.upper(): price})
    if normalized in {"hyperliquid", "hyperliquid_testnet"}:
        return HyperliquidTestnetAdapter(market_prices={coin.upper(): price})
    raise ValueError(f"Unsupported testnet adapter: {name}")


def run_testnet_command(
    settings: Settings,
    *,
    adapter_name: str,
    action: str,
    coin: str,
    side: str,
    notional_usdc: float,
    limit_price: float,
    confirm_testnet: bool,
    dry_confirmed: bool,
    journal_path: Path | None = None,
) -> TestnetRunCommandResult:
    if dry_confirmed:
        settings = build_testnet_runtime_settings(settings, confirmed=confirm_testnet)
    adapter = build_testnet_adapter(adapter_name, price=limit_price, coin=coin)
    journal = TestnetDecisionJournal(journal_path or default_testnet_journal_path())
    executor = TestnetExecutor(settings=settings, adapter=adapter, journal=journal)
    request = TestnetOrderRequest(
        cloid=f"testnet-{coin.lower()}-{action.lower()}",
        action=TestnetAction(action.lower()),
        coin=coin,
        side=TestnetSide(side.lower()),
        notional_usdc=notional_usdc,
        limit_price=limit_price,
        reduce_only=action.lower() in {"reduce", "close"},
        evidence={
            "cli": "testnet-run",
            "dry_confirmed": dry_confirmed,
            "adapter_name": adapter_name,
            "confirmation": confirm_testnet,
        },
    )
    if request.action is TestnetAction.OPEN:
        result = executor.open_position(request, confirmed=confirm_testnet)
    elif request.action is TestnetAction.REDUCE:
        result = executor.reduce_position(request, confirmed=confirm_testnet)
    else:
        result = executor.close_position(request.coin, request.side, cloid=request.cloid, confirmed=confirm_testnet, evidence=request.evidence)

    payload = build_testnet_dashboard_payload(adapter, journal_path=journal.path)
    payload["last_order_result"] = result.to_dict()
    return TestnetRunCommandResult(
        status=result.status,
        adapter=adapter.name,
        action=request.action.value,
        payload=payload,
        journal_path=str(journal.path),
    )


def build_testnet_status(settings: Settings, *, adapter_name: str = "fake", coin: str = "BTC", price: float = 60_000.0) -> dict[str, object]:
    adapter = build_testnet_adapter(adapter_name, price=price, coin=coin)
    payload = build_testnet_dashboard_payload(adapter, journal_path=default_testnet_journal_path())
    payload["config"] = {
        "environment": settings.environment.value,
        "real_mainnet_trading": settings.execution.real_mainnet_trading,
        "testnet_only": settings.execution.testnet_only,
        "testnet_mode": settings.execution.testnet_mode,
        "testnet_execution_enabled": settings.execution.testnet_execution_enabled,
        "confirm_testnet_execution": settings.execution.confirm_testnet_execution,
        "max_testnet_notional": settings.execution.max_testnet_notional,
        "max_open_testnet_positions": settings.execution.max_open_testnet_positions,
    }
    return payload
