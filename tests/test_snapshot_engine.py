import pytest
from hl_observer.wallets.snapshot_engine import SnapshotEngine, SnapshotData
from hl_observer.wallets.position_delta_engine import PositionAction, PositionSide

def test_snapshot_engine_baseline():
    engine = SnapshotEngine()
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        positions=[{"coin": "BTC", "szi": "1.0"}]
    )
    result = engine.compare_snapshots(current, previous=None)
    assert result.is_baseline is True
    assert not result.deltas

def test_snapshot_engine_delta_detection():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[{"coin": "BTC", "szi": "1.0"}]
    )
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        positions=[{"coin": "BTC", "szi": "1.5"}],
        fills=[{"coin": "BTC", "sz": "0.5", "side": "B", "time": 1500, "px": "50000"}]
    )
    result = engine.compare_snapshots(current, previous=previous)
    assert not result.is_baseline
    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert delta.coin == "BTC"
    assert delta.action == PositionAction.ADD
    assert delta.delta_size == 0.5

def test_snapshot_engine_staleness():
    engine = SnapshotEngine(max_staleness_ms=1000)
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[]
    )
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=3000,
        exchange_ts=3000,
        positions=[]
    )
    result = engine.compare_snapshots(current, previous=previous)
    assert result.refused is True
    assert "too old" in result.refusal_reason

def test_snapshot_engine_contradiction():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[{"coin": "BTC", "szi": "1.0"}]
    )
    # Position changed to 2.0 but no fills
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        positions=[{"coin": "BTC", "szi": "2.0"}],
        fills=[]
    )
    result = engine.compare_snapshots(current, previous=previous)
    assert len(result.deltas) == 1
    assert result.deltas[0].action == PositionAction.UNKNOWN
    assert any("without fills" in w for w in result.warnings)

def test_snapshot_engine_missing_data():
    engine = SnapshotEngine()
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        all_mids={} # Missing
    )
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=500,
        exchange_ts=500,
        positions=[]
    )
    result = engine.compare_snapshots(current, previous=previous)
    assert any("Missing allMids" in w for w in result.warnings)
