import json
import os
from dataclasses import dataclass
from typing import Any

@dataclass
class PaginatedFills:
    fills: list[dict[str, Any]]
    stopped_reason: str
    warnings: list[str]

class FakeHyperliquidInfoClient:
    """
    A fake client that returns data from fixtures based on wallet address.

    Mapping:
    - 0x1...1 -> OPEN_LONG (default)
    - 0x2...2 -> CLOSE_LONG
    - 0x3...3 -> ADD / INCREASE
    """
    def __init__(self, fixture_dir="tests/fixtures/hypersmart"):
        self.fixture_dir = fixture_dir

    def _load(self, name):
        path = os.path.join(self.fixture_dir, name)
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def get_clearinghouse_state(self, user):
        user = user.lower()
        if "2222" in user:
            return self._load("info_clearinghouse_state_curr_close_long.json")
        return self._load("info_clearinghouse_state_curr_open_long.json")

    def collect_user_fills_by_time_paginated(self, user, start_time_ms, end_time_ms, max_pages=None):
        user = user.lower()
        if "2222" in user:
            fills = self._load("info_user_fills_close_long_with_closed_pnl.json")
        else:
            fills = self._load("info_user_fills_open_long.json")
        return PaginatedFills(fills=fills, stopped_reason="empty_response", warnings=[])

    def get_user_fills(self, user, *, aggregate_by_time: bool = False):
        user = user.lower()
        if "2222" in user:
            return self._load("info_user_fills_close_long_with_closed_pnl.json")
        return self._load("info_user_fills_open_long.json")

    def get_all_mids(self):
        return self._load("info_all_mids.json")

    def get_open_orders(self, user):
        return self._load("info_open_orders_context_only.json")

    def get_frontend_open_orders(self, user):
        return []

    def get_user_fees(self, user):
        return {"user": user, "daily_fee_discount": "0", "fee_rate_bps": "4.0"}

    def get_user_rate_limit(self, user):
        return {"user": user, "weight": 0}
