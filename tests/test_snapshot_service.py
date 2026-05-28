import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from hl_observer.storage.database import Base
from hl_observer.storage.models import RawEvent, MarketSnapshot, WalletSnapshot
from hl_observer.wallets.snapshot_service import record_robust_snapshot
from hl_observer.utils.time import now_ms

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def test_record_robust_snapshot_baseline(session):
    wallet = "0x123"
    # Seed some data
    session.add(RawEvent(
        source="test",
        request_type="clearinghouseState",
        wallet_address=wallet,
        response_payload_json={"assetPositions": [{"position": {"coin": "BTC", "szi": "1.0"}}]},
        response_hash="hash1",
        fetched_at_ms=now_ms(),
        local_received_ts=now_ms(),
        payload_hash="hash1"
    ))
    session.commit()

    record_robust_snapshot(session, wallet, source="test-run")

    snapshot = session.query(WalletSnapshot).filter_by(wallet_address=wallet).first()
    assert snapshot is not None
    assert snapshot.source == "test-run"
    assert snapshot.positions_json == [{"position": {"coin": "BTC", "szi": "1.0"}}]

def test_record_robust_snapshot_with_delta(session):
    wallet = "0x123"
    # Baseline
    session.add(WalletSnapshot(
        wallet_address=wallet,
        exchange_ts=1000,
        positions_json=[]
    ))
    # New state
    session.add(RawEvent(
        source="test",
        request_type="clearinghouseState",
        wallet_address=wallet,
        response_payload_json={"assetPositions": [{"position": {"coin": "BTC", "szi": "1.0"}}]},
        response_hash="hash2",
        fetched_at_ms=2000,
        exchange_ts=2000,
        local_received_ts=2000,
        payload_hash="hash2"
    ))
    # Fills to match
    from hl_observer.storage.repositories import CollectionRepository
    repo = CollectionRepository(session)
    repo.store_fills(wallet, [{"coin": "BTC", "sz": "1.0", "side": "B", "time": 1500, "px": "50000"}])

    session.commit()

    record_robust_snapshot(session, wallet, source="test-run")

    from hl_observer.storage.models import PositionDeltaModel
    delta = session.query(PositionDeltaModel).filter_by(wallet_address=wallet, coin="BTC").first()
    assert delta is not None
    assert delta.action == "OPEN"
    assert delta.is_paper_eligible is True
