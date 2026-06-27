from __future__ import annotations

import asyncio

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.data_sources.acquisition_engine import RequestBudgetManager
from hl_observer.data_sources.historical_backfill_engine import (
    BackfillStopReason,
    BackoffPolicy,
    HistoricalBackfillConfig,
    HistoricalBackfillEngine,
    TtlPageCache,
)


WALLET = "0x" + "1" * 40


def run(coro):
    return asyncio.run(coro)


def test_historical_backfill_paginates_until_empty_response() -> None:
    calls: list[tuple[int, int]] = []

    async def fetch(_wallet: str, start: int, end: int, _aggregate: bool):
        calls.append((start, end))
        if len(calls) == 1:
            return [{"time": start + 1, "coin": "BTC"}]
        return []

    engine = HistoricalBackfillEngine(
        fetch_page=fetch,
        budget=RequestBudgetManager(network_read_enabled=True),
        config=HistoricalBackfillConfig(max_pages_per_wallet=5, page_window_ms=1_000),
    )

    result = run(engine.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=5_000, now_ms=5_000))

    assert result.pages_fetched == 1
    assert len(result.fills) == 1
    assert result.stopped_reason == BackfillStopReason.EMPTY_RESPONSE
    assert calls == [(0, 1000), (1001, 2001)]


def test_historical_backfill_respects_max_pages() -> None:
    async def fetch(_wallet: str, start: int, _end: int, _aggregate: bool):
        return [{"time": start + 1, "coin": "ETH"}]

    engine = HistoricalBackfillEngine(
        fetch_page=fetch,
        budget=RequestBudgetManager(network_read_enabled=True),
        config=HistoricalBackfillConfig(max_pages_per_wallet=2, page_window_ms=1_000),
    )

    result = run(engine.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=10_000, now_ms=10_000))

    assert result.pages_fetched == 2
    assert result.stopped_reason == BackfillStopReason.MAX_PAGES_REACHED


def test_historical_backfill_stops_on_timestamp_not_progressing() -> None:
    async def fetch(_wallet: str, _start: int, _end: int, _aggregate: bool):
        return [{"coin": "BTC"}]

    engine = HistoricalBackfillEngine(
        fetch_page=fetch,
        budget=RequestBudgetManager(network_read_enabled=True),
        config=HistoricalBackfillConfig(max_pages_per_wallet=5, page_window_ms=1_000),
    )

    result = run(engine.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=10_000, now_ms=10_000))

    assert result.stopped_reason == BackfillStopReason.PAGE_QUALITY_REJECTED
    assert "DATA_TIMESTAMP_MISSING" in result.warnings


def test_historical_backfill_blocks_when_network_read_disabled() -> None:
    async def fetch(_wallet: str, _start: int, _end: int, _aggregate: bool):
        raise AssertionError("fetch should not run")

    engine = HistoricalBackfillEngine(
        fetch_page=fetch,
        budget=RequestBudgetManager(network_read_enabled=False),
        config=HistoricalBackfillConfig(max_pages_per_wallet=1),
    )

    result = run(engine.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=1_000, now_ms=1_000))

    assert result.stopped_reason == BackfillStopReason.NETWORK_READ_DISABLED
    assert result.pages_fetched == 0


def test_historical_backfill_cache_hit_does_not_consume_budget() -> None:
    calls = 0
    cache = TtlPageCache(ttl_ms=60_000)
    budget = RequestBudgetManager(network_read_enabled=True, rest_weight_remaining=1)

    async def fetch(_wallet: str, start: int, _end: int, _aggregate: bool):
        nonlocal calls
        calls += 1
        return [{"time": start + 1, "coin": "BTC"}]

    config = HistoricalBackfillConfig(max_pages_per_wallet=1, page_window_ms=1_000)
    first = HistoricalBackfillEngine(fetch_page=fetch, budget=budget, cache=cache, config=config)
    second = HistoricalBackfillEngine(fetch_page=fetch, budget=budget, cache=cache, config=config)

    result1 = run(first.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=1_000, now_ms=1_000))
    result2 = run(second.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=1_000, now_ms=1_000))

    assert result1.cache_hits == 0
    assert result2.cache_hits == 1
    assert calls == 1
    assert budget.rest_weight_remaining == 0
    assert result2.stopped_reason == BackfillStopReason.COMPLETED


def test_historical_backfill_backoff_records_delays() -> None:
    calls = 0
    slept: list[float] = []

    async def fetch(_wallet: str, start: int, _end: int, _aggregate: bool):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return [{"time": start + 1, "coin": "BTC"}]

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    engine = HistoricalBackfillEngine(
        fetch_page=fetch,
        budget=RequestBudgetManager(network_read_enabled=True),
        backoff=BackoffPolicy(base_delay_ms=100, max_delay_ms=1000),
        sleep=sleep,
        config=HistoricalBackfillConfig(max_pages_per_wallet=1, max_retries=1),
    )

    result = run(engine.run_user_fills_by_time(wallet_address=WALLET, start_time_ms=0, end_time_ms=1_000, now_ms=1_000))

    assert calls == 2
    assert slept == [0.1]
    assert result.backoff_delays_ms == (100,)
    assert result.warnings == ("FETCH_ERROR:RuntimeError",)


def test_historical_backfill_cli_is_read_only_and_bounded() -> None:
    result = CliRunner().invoke(app, ["historical-backfill-plan", "--network-read", "--max-pages", "1", "--page-items", "1"])

    assert result.exit_code == 0
    assert "historical_backfill=read_only_bounded" in result.output
    assert "stopped_reason=COMPLETED" in result.output
    assert "execution=forbidden" in result.output
    assert "profit_guarantee=false" in result.output
