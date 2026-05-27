import pytest
from sqlalchemy.orm import Session
from hl_observer.storage.database import create_sqlite_engine, create_session_factory, Base
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.storage.models import SourceHealth, FreshnessStatus
from hl_observer.utils.time import now_ms

@pytest.fixture
def session():
    engine = create_sqlite_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session

def test_update_source_health_fresh(session):
    repo = CollectionRepository(session)
    now = now_ms()
    health = repo.update_source_health("test_source", is_success=True, event_timestamp_ms=now)

    assert health.source_name == "test_source"
    assert health.freshness_status == FreshnessStatus.FRESH
    assert health.seconds_since_last_event == 0

def test_update_source_health_stale(session):
    repo = CollectionRepository(session)
    # 15 seconds ago
    ts = now_ms() - 15000
    health = repo.update_source_health("test_source", is_success=True, event_timestamp_ms=ts)

    assert health.freshness_status == FreshnessStatus.STALE
    assert health.seconds_since_last_event >= 15

def test_update_source_health_dead(session):
    repo = CollectionRepository(session)
    # 70 seconds ago
    ts = now_ms() - 70000
    health = repo.update_source_health("test_source", is_success=True, event_timestamp_ms=ts)

    assert health.freshness_status == FreshnessStatus.DEAD
    assert health.seconds_since_last_event >= 70

def test_get_source_health_map(session):
    repo = CollectionRepository(session)
    repo.update_source_health("source1")
    repo.update_source_health("source2")
    session.commit()

    health_map = repo.get_source_health_map()
    assert len(health_map) == 2
    assert "source1" in health_map
    assert "source2" in health_map

def test_update_source_health_delayed(session):
    repo = CollectionRepository(session)
    # 5 seconds latency, but it was just received
    now = now_ms()
    health = repo.update_source_health("test_source", is_success=True, event_timestamp_ms=now - 5000)

    assert health.freshness_status == FreshnessStatus.DELAYED
    assert health.observed_latency_ms >= 5000

def test_update_source_health_contradictory(session):
    repo = CollectionRepository(session)
    health = repo.update_source_health("test_source", is_consistent=False)

    assert health.freshness_status == FreshnessStatus.CONTRADICTORY
