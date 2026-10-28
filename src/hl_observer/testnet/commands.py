from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hl_observer.config.settings import Settings
from hl_observer.testnet.safety import TESTNET_DISABLED_REASON


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
    return TestnetRunCommandResult(
        status="rejected",
        adapter="disabled_by_scope",
        action=action.strip().lower(),
        payload={
            "mode": "DISABLED_BY_SCOPE",
            "paper_read_only": True,
            "orders_created": 0,
            "pnl_status": "UNMEASURABLE",
            "reason": TESTNET_DISABLED_REASON,
        },
        journal_path="not created: disabled by policy",
    )


def build_testnet_status(settings: Settings, *, adapter_name: str = "fake", coin: str = "BTC", price: float = 60_000.0) -> dict[str, object]:
    return {
        "mode": "DISABLED_BY_SCOPE",
        "environment": "paper",
        "adapter": "not initialized",
        "orders_enabled": False,
        "pnl_status": "UNMEASURABLE",
        "reason": TESTNET_DISABLED_REASON,
    }
