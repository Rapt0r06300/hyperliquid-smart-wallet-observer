from __future__ import annotations

import math

from hl_observer.collection.binance_depth_book import (
    APPLIQUE,
    DESYNC_GAP,
    DESYNC_PREMIER,
    BinanceDepthBook,
)
from hl_observer.collection.binance_depth_orchestrator import (
    BUFFERISE,
    BinanceDepthOrchestrator,
)


def _seed_book(book: BinanceDepthBook, last_update_id: int = 100) -> None:
    book.appliquer_snapshot(
        last_update_id=last_update_id,
        bids=[[100.0, 1.0]],
        asks=[[101.0, 1.0]],
    )


def test_bug021_snapshot_replays_buffered_deltas_after_initial_snapshot() -> None:
    orchestrator = BinanceDepthOrchestrator()

    assert orchestrator.sur_diff(U=101, u=102, bids=[[100.0, 2.0]]) == BUFFERISE
    report = orchestrator.sur_snapshot(
        last_update_id=100,
        bids=[[99.0, 1.0]],
        asks=[[101.0, 1.0]],
    )

    assert report["applied_from_buffer"] == 1
    assert report["needs_snapshot"] is False
    assert orchestrator.book.bids[100.0] == 2.0


def test_bug022_first_delta_above_expected_range_is_fail_closed() -> None:
    book = BinanceDepthBook()
    _seed_book(book)

    result = book.appliquer_diff(U=103, u=104, bids=[[100.0, 2.0]])

    assert result.status == DESYNC_PREMIER
    assert book.exploitable() is False
    assert book.desync is not None


def test_bug023_delta_start_lower_than_next_expected_id_is_rejected() -> None:
    book = BinanceDepthBook()
    _seed_book(book)

    assert book.appliquer_diff(U=101, u=102, bids=[[100.0, 2.0]]).status == APPLIQUE
    result = book.appliquer_diff(U=102, u=103, bids=[[100.0, 3.0]])

    assert result.status == DESYNC_GAP
    assert book.exploitable() is False


def test_bug024_future_delta_after_network_loss_requires_resnapshot() -> None:
    orchestrator = BinanceDepthOrchestrator()
    orchestrator.sur_snapshot(
        last_update_id=100,
        bids=[[100.0, 1.0]],
        asks=[[101.0, 1.0]],
    )
    assert orchestrator.sur_diff(U=101, u=102, bids=[[100.0, 1.5]]) == APPLIQUE

    status = orchestrator.sur_diff(U=105, u=106, bids=[[100.0, 2.0]])

    assert status == DESYNC_GAP
    assert orchestrator.besoin_resnapshot() is True
    assert orchestrator.gap_count == 1


def test_bug025_futures_pu_must_match_previous_update() -> None:
    book = BinanceDepthBook(futures=True)
    _seed_book(book)

    assert book.appliquer_diff(U=101, u=102, pu=100).status == APPLIQUE
    result = book.appliquer_diff(U=103, u=104, pu=999, bids=[[100.0, 3.0]])

    assert result.status == DESYNC_GAP
    assert "PU_DISCONTINU" in (result.detail or "")


def test_bug026_zero_quantity_removes_an_existing_level() -> None:
    book = BinanceDepthBook()
    _seed_book(book)

    assert book.appliquer_diff(U=101, u=101, bids=[[100.0, 0.0]]).status == APPLIQUE

    assert 100.0 not in book.bids
    assert book.best_bid() is None
    assert book.exploitable() is False


def test_bug027_non_finite_price_is_quarantined() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(
        last_update_id=100,
        bids=[[math.nan, 1.0], [100.0, 1.0]],
        asks=[[101.0, 1.0]],
    )

    assert book.invalid_levels == 1
    assert all(math.isfinite(price) for price in book.bids)


def test_bug028_negative_quantity_is_quarantined() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(
        last_update_id=100,
        bids=[[100.0, -1.0], [99.0, 1.0]],
        asks=[[101.0, 1.0]],
    )

    assert book.invalid_levels == 1
    assert 100.0 not in book.bids
    assert book.exploitable() is True


def test_bug029_crossed_book_is_not_exploitable_or_publishable_as_good() -> None:
    orchestrator = BinanceDepthOrchestrator()
    orchestrator.sur_snapshot(
        last_update_id=100,
        bids=[[101.0, 1.0]],
        asks=[[100.0, 1.0]],
    )

    publication = orchestrator.publier()

    assert publication["quality"] == "DESYNC"
    assert publication["needs_resnapshot"] is True
    assert publication["exploitable"] is False


def test_bug030_duplicate_bid_price_has_one_canonical_level() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(
        last_update_id=100,
        bids=[[100.0, 1.0], [100.0, 2.0]],
        asks=[[101.0, 1.0]],
    )

    assert book.bids == {100.0: 2.0}
    assert book.snapshot()["bids"] == [[100.0, 2.0]]
