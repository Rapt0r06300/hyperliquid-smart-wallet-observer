"""Deterministic PAPER/READ-ONLY guards for Copy-Vault BUG-011..020.

These tests exercise the active Hyperliquid collection and parsing paths.  They
prove rejection, bounded pagination, and explicit separation of observations;
they do not turn missing external observations into synthetic evidence.
"""

from __future__ import annotations

import asyncio

import pytest

from hl_observer.collection.copy_vault_checkpoint_tail import coverage_receipt
from hl_observer.collection.vault_fills_backfill import (
    CAP_USERFILLS,
    plan_de_requetes,
    split_inclusive_window,
)
from hl_observer.hyperliquid.rest_info_client import (
    MAX_USER_FILLS_PAGE_SIZE,
    HyperliquidInfoClient,
    HyperliquidInfoError,
    build_open_orders_payload,
    build_user_fills_payload,
    build_user_fills_by_time_payload,
)
from hl_observer.hyperliquid.ws_client import (
    MarketWebSocketClient,
    MarketWebSocketConfig,
)


def _book(levels: int = 8) -> dict[str, object]:
    return {
        "time": 1_000,
        "levels": [
            [{"px": str(100 - i), "sz": "1"} for i in range(levels)],
            [{"px": str(101 + i), "sz": "1"} for i in range(levels)],
        ],
    }


def test_bug_011_snapshot_stream_gap_is_unmeasurable_not_zero() -> None:
    receipt = coverage_receipt(
        {"complete_lines": 2, "checkpoints_captured": 1, "reconnect_backfill_blocked": 1, "invalid_rejected": 0},
        expected_lines=3,
    )
    assert receipt["status"] == "UNMEASURABLE"
    assert receipt["gap_count"] == 1


def test_bug_012_inclusive_reconnect_windows_do_not_overlap() -> None:
    assert split_inclusive_window(0, 9) == ((0, 4), (5, 9))
    assert split_inclusive_window(0, 1) == ((0, 0), (1, 1))
    assert split_inclusive_window(0, 0) is None


def test_bug_013_pagination_plan_is_bounded_and_ordered() -> None:
    windows = plan_de_requetes(0, 3 * 60 * 60 * 1000, fenetre_ms=60 * 60 * 1000)
    assert windows
    assert windows[0][0] == 0
    assert windows[-1][1] == 3 * 60 * 60 * 1000
    assert all(left <= right for left, right in windows)
    assert all(previous[1] < current[0] for previous, current in zip(windows, windows[1:]))


def test_bug_014_api_response_cap_rejects_unbounded_page() -> None:
    async def scenario() -> None:
        client = object.__new__(HyperliquidInfoClient)
        pages = client._iter_user_fills_by_time_windows(
            "0xvault",
            1,
            2,
            response_cap=MAX_USER_FILLS_PAGE_SIZE + 1,
        )
        with pytest.raises(HyperliquidInfoError, match="response cap"):
            await anext(pages)

    asyncio.run(scenario())


def test_bug_015_user_websocket_opt_in_remains_fail_closed() -> None:
    client = MarketWebSocketClient(MarketWebSocketConfig(subscribe_user_streams=True))
    with pytest.raises(RuntimeError, match="disabled"):
        client.assert_safe()


def test_bug_016_l2_parser_bounds_depth_to_five_levels() -> None:
    from hl_observer.collection.copy_vault_checkpoint_tail import _parse_book

    parsed = _parse_book(_book(), received_at_ms=1_001)
    assert parsed is not None
    assert len(parsed["bids5"]) == 5
    assert len(parsed["asks5"]) == 5


def test_bug_017_l2_parser_rejects_crossed_or_stale_book() -> None:
    from hl_observer.collection.copy_vault_checkpoint_tail import _parse_book

    crossed = {"time": 1_000, "levels": [[{"px": "102", "sz": "1"}], [{"px": "101", "sz": "1"}]]}
    stale = _book(1)
    assert _parse_book(crossed, received_at_ms=1_001) is None
    assert _parse_book(stale, received_at_ms=1_000 + 30_001) is None


def test_bug_018_fills_payload_rejects_reversed_window() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        build_user_fills_by_time_payload("0xvault", 2_000, 1_000)


def test_bug_019_funding_history_cap_is_explicit() -> None:
    assert CAP_USERFILLS == 2_000
    assert build_user_fills_payload("0xvault", aggregate_by_time=True)["aggregateByTime"] is True


def test_bug_020_open_orders_are_not_fills() -> None:
    open_orders = build_open_orders_payload("0xvault")
    fills = build_user_fills_payload("0xvault")
    assert open_orders["type"] == "openOrders"
    assert fills["type"] == "userFills"
    assert open_orders != fills
