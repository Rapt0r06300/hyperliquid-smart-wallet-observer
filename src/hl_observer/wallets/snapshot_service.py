from __future__ import annotations

import logging
from typing import Any, Optional
from sqlalchemy.orm import Session

from hl_observer.storage.models import RawEvent, MarketSnapshot, Position, OpenOrder, Fill
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.wallets.snapshot_engine import SnapshotEngine, SnapshotData
from hl_observer.utils.time import now_ms

logger = logging.getLogger(__name__)

def record_robust_snapshot(
    session: Session,
    wallet_address: str,
    run_id: Optional[int] = None,
    source: str = "manual",
    stopped_reason: Optional[str] = None,
    errors: Optional[list[str]] = None,
    echo_func: Optional[callable] = None
) -> None:
    """
    Builds a robust SnapshotData from current DB state, compares with previous,
    stores the new snapshot, and handles deltas.
    """
    try:
        repo = CollectionRepository(session)
        engine = SnapshotEngine()

        # 1. Gather latest raw data and context
        # Use a join or a combined query if possible for performance, but here we keep it clear.
        latest_raw = session.query(RawEvent).filter(
            RawEvent.wallet_address == wallet_address
        ).order_by(RawEvent.id.desc()).first()

        latest_mids = session.query(MarketSnapshot).order_by(MarketSnapshot.id.desc()).first()

        # 2. Get latest clearinghouse state if available
        ch_event = session.query(RawEvent).filter(
            RawEvent.wallet_address == wallet_address,
            RawEvent.request_type == "clearinghouseState"
        ).order_by(RawEvent.id.desc()).first()

        positions_to_use = []
        if ch_event and ch_event.response_payload_json:
            positions_to_use = ch_event.response_payload_json.get("assetPositions", [])
        else:
            # Fallback to reconstructed positions
            db_positions = session.query(Position).filter(Position.wallet_address == wallet_address).all()
            positions_to_use = [p.raw_json for p in db_positions if p.raw_json]

        # Fetch only what's needed for the snapshot
        db_orders = session.query(OpenOrder.raw_json).filter(OpenOrder.wallet_address == wallet_address).all()
        db_fills = session.query(Fill.raw_json).filter(
            Fill.wallet_address == wallet_address
        ).order_by(Fill.exchange_ts.desc()).limit(100).all()

        # 3. Build snapshot data
        snapshot_data = SnapshotData(
            wallet_address=wallet_address,
            collection_run_id=run_id,
            local_received_ts=now_ms(),
            exchange_ts=latest_raw.exchange_ts if latest_raw else now_ms(),
            positions=positions_to_use,
            open_orders=[o[0] for o in db_orders if o[0]],
            fills=[f[0] for f in db_fills if f[0]],
            all_mids=latest_mids.raw_json if latest_mids else {},
            source=source,
            stopped_reason=stopped_reason,
            errors=errors or []
        )

        # 4. Compare with previous
        previous_model = repo.get_latest_wallet_snapshot(wallet_address)
        previous_data = engine.from_model(previous_model) if previous_model else None

        comparison = engine.compare_snapshots(snapshot_data, previous_data)

        # 5. Store new snapshot
        current_snapshot_model = repo.store_wallet_snapshot(
            wallet_address=wallet_address,
            raw_json=snapshot_data.model_dump(),
            collection_run_id=snapshot_data.collection_run_id,
            local_received_ts=snapshot_data.local_received_ts,
            exchange_ts=snapshot_data.exchange_ts,
            positions=snapshot_data.positions,
            open_orders=snapshot_data.open_orders,
            fills=snapshot_data.fills,
            all_mids=snapshot_data.all_mids,
            source=snapshot_data.source,
            stopped_reason=snapshot_data.stopped_reason,
            errors=snapshot_data.errors + comparison.errors
        )
        current_snapshot_model.summary = comparison.summary()
        session.flush() # Ensure ID is generated for reporting
        comparison.current_snapshot_id = current_snapshot_model.id
        if previous_model:
            comparison.previous_snapshot_id = previous_model.id

        # 6. Report findings
        if echo_func:
            echo_func(f"Snapshot for {wallet_address}: {comparison.summary()}")
            for warn in comparison.warnings:
                echo_func(f"  [WARN] {warn}")

        # 7. Store deltas
        if comparison.deltas:
            # Important: link deltas to the snapshot ID for audit trail
            for d in comparison.deltas:
                d.snapshot_id = current_snapshot_model.id
            repo.store_position_deltas(comparison.deltas)
            if echo_func:
                echo_func(f"  [INFO] Recorded {len(comparison.deltas)} deltas from snapshot")

    except Exception as exc:
        logger.error(f"Failed to record robust snapshot for {wallet_address}: {exc}")
        if echo_func:
            echo_func(f"  [ERROR] Snapshot failed for {wallet_address}: {exc}")
