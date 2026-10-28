from __future__ import annotations

from pathlib import Path

from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.safety import TESTNET_DISABLED_REASON


def build_testnet_dashboard_payload(adapter: TestnetExchangeAdapter, *, journal_path: Path | None = None) -> dict[str, object]:
    del adapter, journal_path
    return {
        "mode": "DISABLED_BY_SCOPE",
        "environment": "paper",
        "orders_enabled": False,
        "open_positions": None,
        "pnl_status": "UNMEASURABLE",
        "reason": TESTNET_DISABLED_REASON,
    }
