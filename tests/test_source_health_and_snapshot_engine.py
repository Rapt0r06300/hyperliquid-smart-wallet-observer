from __future__ import annotations

import pytest

from hl_observer.storage.database import Base, create_session_factory, create_sqlite_engine
from hl_observer.storage.models import FreshnessStatus
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms
from hl_observer.wallets.position_delta_engine import PositionAction
from hl_observer.wallets.snapshot_engine import SnapshotData, SnapshotEngine


@pytest.fixture
def repo():
    engine = create_sqlite_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield CollectionRepository(session)


def test_source_health_records_fresh_stale_dead_and_contradictory(repo: CollectionRepository):
    assert repo.update_source_health("allMids", event_timestamp_ms=now_ms()).freshness_status == FreshnessStatus.FRESH
    assert (
        repo.update_source_health("leader_fills", event_timestamp_ms=now_ms() - 15_000).freshness_status
        == FreshnessStatus.STALE
    )
    assert (
        repo.update_source_health("public_trades", event_timestamp_ms=now_ms() - 70_000).freshness_status
        == FreshnessStatus.DEAD
    )
    assert (
        repo.update_source_health("snapshot", is_consistent=False).freshness_status
        == FreshnessStatus.CONTRADICTORY
    )


def test_snapshot_engine_baseline_then_open_long_delta():
    engine = SnapshotEngine()
    baseline = SnapshotData(
        wallet_address="0x" + "1" * 40,
        local_received_ts=1_000,
        exchange_ts=1_000,
        positions=[],
        all_mids={"BTC": "50000"},
    )
    assert engine.compare_snapshots(baseline).is_baseline is True

    current = SnapshotData(
        wallet_address=baseline.wallet_address,
        local_received_ts=2_000,
        exchange_ts=2_000,
        positions=[{"position": {"coin": "BTC", "szi": "1.0", "entryPx": "50000"}}],
        fills=[{"coin": "BTC", "side": "B", "sz": "1.0", "px": "50000", "time": 1_500}],
        all_mids={"BTC": "50000"},
    )
    result = engine.compare_snapshots(current, baseline)

    assert result.is_baseline is False
    assert len(result.deltas) == 1
    assert result.deltas[0].action == PositionAction.OPEN
    assert result.deltas[0].is_paper_eligible is True
    assert result.deltas[0].proofs["size_match"] is True


def test_snapshot_engine_refuses_position_change_without_matching_fills():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x" + "2" * 40,
        local_received_ts=1_000,
        exchange_ts=1_000,
        positions=[{"coin": "ETH", "szi": "1.0"}],
        all_mids={"ETH": "2500"},
    )
    current = SnapshotData(
        wallet_address=previous.wallet_address,
        local_received_ts=2_000,
        exchange_ts=2_000,
        positions=[{"coin": "ETH", "szi": "2.0"}],
        fills=[],
        all_mids={"ETH": "2500"},
    )

    result = engine.compare_snapshots(current, previous)

    assert len(result.deltas) == 1
    assert result.deltas[0].action == PositionAction.UNKNOWN
    assert result.deltas[0].is_paper_eligible is False
    assert "position_change_without_matching_fills" in result.deltas[0].notes


def test_snapshot_engine_flip_stays_unknown():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x" + "3" * 40,
        local_received_ts=1_000,
        exchange_ts=1_000,
        positions=[{"coin": "SOL", "szi": "1.0"}],
        all_mids={"SOL": "100"},
    )
    current = SnapshotData(
        wallet_address=previous.wallet_address,
        local_received_ts=2_000,
        exchange_ts=2_000,
        positions=[{"coin": "SOL", "szi": "-1.0"}],
        fills=[{"coin": "SOL", "side": "A", "sz": "2.0", "px": "100", "time": 1_500}],
        all_mids={"SOL": "100"},
    )

    result = engine.compare_snapshots(current, previous)

    assert result.deltas[0].action == PositionAction.UNKNOWN
    assert result.deltas[0].is_paper_eligible is False
    assert "flip_classified_unknown" in result.deltas[0].notes
