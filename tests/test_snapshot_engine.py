import pytest
from hl_observer.wallets.snapshot_engine import SnapshotEngine, SnapshotData, IntelligentDeltaDetector
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

def test_snapshot_engine_clearinghouse_format():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[]
    )
    # Using the nested "position" key format from clearinghouseState
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        positions=[
            {
                "position": {
                    "coin": "ETH",
                    "szi": "2.0",
                    "entryPx": "2500"
                }
            }
        ],
        fills=[{"coin": "ETH", "sz": "2.0", "side": "B", "time": 1500, "px": "2500"}]
    )
    result = engine.compare_snapshots(current, previous=previous)
    assert len(result.deltas) == 1
    assert result.deltas[0].coin == "ETH"
    assert result.deltas[0].new_size == 2.0
    assert result.deltas[0].action == PositionAction.OPEN

def test_snapshot_engine_timestamp_aware_fills():
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
        fills=[
            # This fill is OLD (time 500 < prev exchange_ts 1000), should be ignored
            {"coin": "BTC", "sz": "1.0", "side": "B", "time": 500, "px": "40000"},
            # This fill is NEW, should be counted
            {"coin": "BTC", "sz": "0.5", "side": "B", "time": 1500, "px": "50000"}
        ]
    )
    result = engine.compare_snapshots(current, previous=previous)
    # If it ignored the old fill, delta is 0.5, total 1.0+0.5=1.5 -> matches position -> SUCCESS
    assert result.deltas[0].action == PositionAction.ADD
    assert not any("Contradiction" in w for w in result.warnings)

def test_snapshot_engine_intelligent_scorecard():
    engine = SnapshotEngine()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[{"coin": "BTC", "szi": "1.0"}]
    )

    # 1. Size match, side alignment -> HIGH confidence
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        positions=[{"coin": "BTC", "szi": "2.0"}],
        fills=[{"coin": "BTC", "sz": "1.0", "side": "B", "time": 1500, "px": "50000"}]
    )
    result = engine.compare_snapshots(current, previous=previous)
    delta = result.deltas[0]
    assert delta.proofs["size_match"] is True
    assert delta.proofs["side_alignment"] is True
    assert delta.confidence_score >= 0.8
    assert delta.is_paper_eligible is True

    # 2. Side contradiction -> UNKNOWN
    current.positions = [{"coin": "BTC", "szi": "0.5"}] # Decrease
    current.fills = [{"coin": "BTC", "sz": "0.5", "side": "B", "time": 1500, "px": "50000"}] # But fill is BUY
    result = engine.compare_snapshots(current, previous=previous)
    delta = result.deltas[0]
    assert delta.proofs["side_alignment"] is False
    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence_score == 0.0
    assert delta.is_paper_eligible is False

    # 3. Position change without fills -> MEDIUM confidence
    current.positions = [{"coin": "BTC", "szi": "2.0"}]
    current.fills = []
    result = engine.compare_snapshots(current, previous=previous)
    delta = result.deltas[0]
    assert delta.proofs["has_fills"] is False
    assert delta.action == PositionAction.UNKNOWN # Since it's a size mismatch (expected 1.0, got 2.0)

    # Let's test a case where it's NOT UNKNOWN but has no fills?
    # Actually, any size mismatch with NO FILLS is UNKNOWN in our logic.

def test_intelligent_delta_detector_grandmaster():
    detector = IntelligentDeltaDetector()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[{"coin": "BTC", "szi": "1.0"}]
    )

    # Complex case: multiple fills, price sanity check, entropy check
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        all_mids={"BTC": "50000"},
        positions=[{"coin": "BTC", "szi": "2.0"}],
        fills=[
            {"coin": "BTC", "sz": "0.6", "side": "B", "time": 1500, "px": "49500", "tid": 101},
            {"coin": "BTC", "sz": "0.4", "side": "B", "time": 1600, "px": "50500", "tid": 102}
        ]
    )
    result = detector.detect_deltas(current, previous=previous)
    delta = result.deltas[0]

    assert delta.proofs["size_match"] is True
    assert delta.proofs["zero_entropy_fills"] is True # Unique TIDs
    assert delta.proofs["market_price_sanity"] is True # Avg px 50000 vs mid 50000
    assert delta.confidence_score >= 0.85
    assert delta.is_paper_eligible is True

def test_intelligent_delta_detector_high_entropy_rejection():
    detector = IntelligentDeltaDetector()
    previous = SnapshotData(
        wallet_address="0x123",
        local_received_ts=1000,
        exchange_ts=1000,
        positions=[]
    )

    # Duplicate TIDs -> High entropy -> Lower confidence
    current = SnapshotData(
        wallet_address="0x123",
        local_received_ts=2000,
        exchange_ts=2000,
        positions=[{"coin": "BTC", "szi": "1.0"}],
        fills=[
            {"coin": "BTC", "sz": "0.5", "side": "B", "time": 1500, "px": "50000", "tid": 999},
            {"coin": "BTC", "sz": "0.5", "side": "B", "time": 1600, "px": "50000", "tid": 999} # Duplicate TID
        ]
    )
    result = detector.detect_deltas(current, previous=previous)
    delta = result.deltas[0]
    assert delta.proofs["zero_entropy_fills"] is False
    assert delta.confidence_score < 1.0
