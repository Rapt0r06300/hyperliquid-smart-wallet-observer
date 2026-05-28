from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient, PaginationResult

FIXTURES_DIR = Path("tests/fixtures/hypersmart")

class FakeHyperliquidInfoClient:
    def __init__(self, config=None):
        self.config = config
        self.call_counts = {}

    def _increment_call(self, name: str):
        self.call_counts[name] = self.call_counts.get(name, 0) + 1

    def _load_fixture(self, filename: str) -> Any:
        path = FIXTURES_DIR / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_all_mids(self) -> dict[str, str]:
        self._increment_call("get_all_mids")
        return self._load_fixture("info_all_mids.json") or {}

    def get_clearinghouse_state(self, address: str) -> dict[str, Any]:
        self._increment_call("get_clearinghouse_state")
        # For simplicity, returning a default open long state if not previous
        if address == "0x1111111111111111111111111111111111111111":
            return self._load_fixture("info_clearinghouse_state_curr_open_long.json") or {}
        return self._load_fixture("info_clearinghouse_state_prev_empty.json") or {}

    def get_user_fills(self, address: str) -> list[dict[str, Any]]:
        self._increment_call("get_user_fills")
        if address == "0x1111111111111111111111111111111111111111":
            return self._load_fixture("info_user_fills_open_long.json") or []
        return []

    def get_user_fills_by_time(self, address: str, start_time_ms: int, end_time_ms: int | None = None) -> list[dict[str, Any]]:
        self._increment_call("get_user_fills_by_time")
        if address == "0x1111111111111111111111111111111111111111":
            return self._load_fixture("info_user_fills_open_long.json") or []
        return []

    def collect_user_fills_by_time_paginated(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        max_pages: int | None = None,
    ) -> PaginationResult:
        self._increment_call("collect_user_fills_by_time_paginated")
        fills = self.get_user_fills_by_time(address, start_time_ms, end_time_ms)
        return PaginationResult(fills=fills, pages_fetched=1, stopped_reason="empty_response")

    def get_open_orders(self, address: str) -> list[dict[str, Any]]:
        self._increment_call("get_open_orders")
        return self._load_fixture("info_open_orders_context_only.json") or []

    def get_frontend_open_orders(self, address: str) -> list[dict[str, Any]]:
        self._increment_call("get_frontend_open_orders")
        return []

    def get_user_fees(self, address: str) -> dict[str, Any]:
        self._increment_call("get_user_fees")
        return {"user": address, "dailyIpLimit": 1200}

    def get_user_rate_limit(self, address: str) -> dict[str, Any]:
        self._increment_call("get_user_rate_limit")
        return {"user": address, "cumVUsd": "0.0", "nRequests": 0}
