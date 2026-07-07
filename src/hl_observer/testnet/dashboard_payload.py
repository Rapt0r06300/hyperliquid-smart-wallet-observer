from __future__ import annotations

from pathlib import Path

from hl_observer.testnet.adapters import TestnetExchangeAdapter
from hl_observer.testnet.portfolio_tracker import TestnetPortfolioTracker


def build_testnet_dashboard_payload(adapter: TestnetExchangeAdapter, *, journal_path: Path | None = None) -> dict[str, object]:
    payload = TestnetPortfolioTracker(adapter).dashboard_payload()
    if journal_path and journal_path.exists():
        lines = journal_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        payload["journal_tail"] = lines[-20:]
        payload["journal_path"] = str(journal_path)
    else:
        payload["journal_tail"] = []
        payload["journal_path"] = str(journal_path) if journal_path else None
    return payload
