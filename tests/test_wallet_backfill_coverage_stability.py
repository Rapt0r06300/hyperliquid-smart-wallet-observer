from __future__ import annotations

import asyncio
from typing import Any

from hl_observer.wallets import backfill


WALLET = "0x1111111111111111111111111111111111111111"


class _FailingClient:
    async def user_fills_by_time(
        self,
        wallet: str,
        start_ms: int,
        end_ms: int,
        *,
        aggregate_by_time: bool,
    ) -> list[dict[str, Any]]:
        assert wallet == WALLET
        assert start_ms == 100
        assert end_ms == 200
        assert aggregate_by_time is False
        raise RuntimeError("read-only info failure")


class _RecordingRepo:
    def __init__(self) -> None:
        self.collection_items: list[dict[str, Any]] = []
        self.health: list[dict[str, Any]] = []
        self.raw: list[dict[str, Any]] = []

    def add_collection_item(self, **kwargs: Any) -> None:
        self.collection_items.append(kwargs)

    def store_api_health(self, **kwargs: Any) -> None:
        self.health.append(kwargs)

    def store_raw_event(self, **kwargs: Any) -> None:
        self.raw.append(kwargs)


def test_user_fills_by_time_network_exception_is_captured_fail_closed() -> None:
    pages = asyncio.run(
        backfill._fetch_user_fills_by_time(
            _FailingClient(),
            WALLET,
            100,
            200,
            100,
            2,
        )
    )

    assert len(pages) == 1
    page, exc, latency_ms = pages[0]
    assert page is None
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "read-only info failure"
    assert latency_ms >= 0


def test_user_fills_by_time_error_page_persists_health_and_raw_trace() -> None:
    repo = _RecordingRepo()
    plan = backfill.WalletBackfillPlan(store_raw=True)
    result = backfill.WalletBackfillResult()
    fills_for_rebuild: list[dict[str, Any]] = []

    backfill._process_fetched_user_fills_by_time(
        repo,
        7,
        plan,
        result,
        WALLET,
        100,
        200,
        fills_for_rebuild,
        [(None, RuntimeError("read-only info failure"), 12)],
    )

    assert result.errors_count == 1
    assert result.raw_events_stored == 1
    assert fills_for_rebuild == []
    assert repo.collection_items == [
        {
            "run_id": 7,
            "item_type": "userFillsByTime",
            "wallet_address": WALLET,
            "status": "error",
            "error_message": "read-only info failure",
        }
    ]
    assert repo.health == [
        {
            "service": "hyperliquid_info:userFillsByTime",
            "ok": False,
            "latency_ms": 12,
            "error": "read-only info failure",
        }
    ]
    assert repo.raw[0]["endpoint"] == "/info"
    assert repo.raw[0]["request_type"] == "userFillsByTime"
    assert repo.raw[0]["success"] is False
    assert repo.raw[0]["error_message"] == "read-only info failure"
