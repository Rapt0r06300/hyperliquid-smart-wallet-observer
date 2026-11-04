from __future__ import annotations

from hl_observer.collection.binance_depth_book import APPLIQUE, DESYNC_PREMIER, BinanceDepthBook
from hl_observer.collection.binance_depth_orchestrator import BUFFERISE, BinanceDepthOrchestrator


def test_bug031_payload_with_one_absent_side_updates_only_the_present_side() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(last_update_id=100, bids=[[100.0, 1.0]], asks=[[101.0, 1.0]])

    result = book.appliquer_diff(U=101, u=101, asks=[[101.0, 2.0]])

    assert result.status == APPLIQUE
    assert book.bids == {100.0: 1.0}
    assert book.asks == {101.0: 2.0}


def test_bug032_snapshot_newer_than_buffer_discards_obsolete_deltas() -> None:
    orchestrator = BinanceDepthOrchestrator()
    assert orchestrator.sur_diff(U=101, u=102, bids=[[100.0, 2.0]]) == BUFFERISE

    report = orchestrator.sur_snapshot(
        last_update_id=200,
        bids=[[100.0, 3.0]],
        asks=[[101.0, 1.0]],
    )

    assert report["applied_from_buffer"] == 0
    assert report["needs_snapshot"] is False
    assert orchestrator.book.bids[100.0] == 3.0


def test_bug033_buffer_overflow_is_visible_and_does_not_fake_contiguity() -> None:
    orchestrator = BinanceDepthOrchestrator(max_buffer=2)
    assert orchestrator.sur_diff(U=101, u=101) == BUFFERISE
    assert orchestrator.sur_diff(U=102, u=102) == BUFFERISE
    assert orchestrator.sur_diff(U=103, u=103) == BUFFERISE

    report = orchestrator.sur_snapshot(last_update_id=100, bids=[[100.0, 1.0]], asks=[[101.0, 1.0]])

    assert report["buffer_overflow_count"] == 1
    assert report["needs_snapshot"] is True
    assert orchestrator.gap_count >= 2


def test_bug034_publication_preserves_exchange_and_receive_timestamps() -> None:
    orchestrator = BinanceDepthOrchestrator()
    orchestrator.sur_snapshot(
        last_update_id=100,
        bids=[[100.0, 1.0]],
        asks=[[101.0, 1.0]],
        exchange_ts_ms=1_000,
        receive_ts_ms=1_025,
        receive_mono_ns=9_000,
        connection_id="conn-1",
    )

    publication = orchestrator.publier()

    assert publication["exchange_ts_ms"] == 1_000
    assert publication["receive_ts_ms"] == 1_025
    assert publication["receive_mono_ns"] == 9_000


def test_bug035_connection_change_forces_a_new_snapshot_anchor() -> None:
    orchestrator = BinanceDepthOrchestrator()
    orchestrator.sur_snapshot(
        last_update_id=100,
        bids=[[100.0, 1.0]],
        asks=[[101.0, 1.0]],
        connection_id="conn-1",
    )

    status = orchestrator.sur_diff(U=101, u=101, connection_id="conn-2")

    assert status == BUFFERISE
    assert orchestrator.besoin_resnapshot() is True
    assert orchestrator.book.desync == "CONNECTION_CHANGED"


def test_bug036_level_precision_is_preserved_in_the_canonical_snapshot() -> None:
    book = BinanceDepthBook()
    price = 100.123456789
    book.appliquer_snapshot(last_update_id=100, bids=[[price, 1.25]], asks=[[101.0, 1.0]])

    assert book.snapshot()["bids"] == [[price, 1.25]]


def test_bug037_bids_are_sorted_from_best_to_worst() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(
        last_update_id=100,
        bids=[[99.0, 1.0], [101.0, 1.0], [100.0, 1.0]],
        asks=[[102.0, 1.0]],
    )

    assert [row[0] for row in book.snapshot(depth=3)["bids"]] == [101.0, 100.0, 99.0]


def test_bug038_asks_are_sorted_from_best_to_worst() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(
        last_update_id=100,
        bids=[[99.0, 1.0]],
        asks=[[103.0, 1.0], [101.0, 1.0], [102.0, 1.0]],
    )

    assert [row[0] for row in book.snapshot(depth=3)["asks"]] == [101.0, 102.0, 103.0]


def test_bug039_reconstructed_bbo_and_mid_match_the_book_source() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(last_update_id=100, bids=[[100.0, 1.0]], asks=[[102.0, 1.0]])

    assert book.best_bid() == 100.0
    assert book.best_ask() == 102.0
    assert book.mid() == 101.0


def test_bug040_incomplete_or_inactive_book_is_not_exploitable() -> None:
    book = BinanceDepthBook()
    book.appliquer_snapshot(last_update_id=100, bids=[[100.0, 1.0]], asks=[])

    assert book.exploitable() is False
    assert book.snapshot()["exploitable"] is False
