from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.storage.models import Fill, MarketSnapshot, OpenOrder, Position, RawEvent
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms
from hl_observer.wallets.snapshot_engine import SnapshotData, SnapshotEngine


def record_robust_snapshot(
    session: Session,
    wallet_address: str,
    *,
    run_id: int | None = None,
    source: str = "manual",
    stopped_reason: str | None = None,
    errors: list[str] | None = None,
    echo_func: Callable[[str], Any] | None = None,
) -> None:
    """Persist a wallet snapshot and store safe deltas against the previous one.

    This is read-only bookkeeping over already-collected local data. It never
    contacts Hyperliquid and never creates an execution action.
    """

    repo = CollectionRepository(session)
    snapshot_engine = SnapshotEngine()

    raw_event = (
        session.query(RawEvent)
        .filter(RawEvent.wallet_address == wallet_address)
        .order_by(RawEvent.id.desc())
        .first()
    )
    clearinghouse_event = (
        session.query(RawEvent)
        .filter(
            RawEvent.wallet_address == wallet_address,
            RawEvent.request_type == "clearinghouseState",
        )
        .order_by(RawEvent.id.desc())
        .first()
    )
    latest_mids = session.query(MarketSnapshot).order_by(MarketSnapshot.id.desc()).first()

    positions_payload = _positions_payload(session, wallet_address, clearinghouse_event)
    orders_payload = [row.raw_json for row in session.query(OpenOrder).filter(OpenOrder.wallet_address == wallet_address).all()]
    fills_payload = [
        row.raw_json
        for row in session.query(Fill)
        .filter(Fill.wallet_address == wallet_address)
        .order_by(Fill.exchange_ts.desc(), Fill.id.desc())
        .limit(250)
        .all()
    ]
    snapshot = SnapshotData(
        wallet_address=wallet_address,
        collection_run_id=run_id,
        local_received_ts=now_ms(),
        exchange_ts=raw_event.exchange_ts if raw_event and raw_event.exchange_ts else now_ms(),
        positions=positions_payload,
        open_orders=orders_payload,
        frontend_open_orders=[],
        fills=fills_payload,
        all_mids=latest_mids.raw_json if latest_mids and isinstance(latest_mids.raw_json, dict) else {},
        source=source,
        stopped_reason=stopped_reason,
        errors=errors or [],
        raw_json={
            "source": source,
            "wallet_address": wallet_address,
            "positions_count": len(positions_payload),
            "fills_count": len(fills_payload),
            "open_orders_count": len(orders_payload),
            "research_only": True,
        },
    )
    previous_model = repo.get_latest_wallet_snapshot(wallet_address)
    previous = snapshot_engine.from_model(previous_model) if previous_model else None
    comparison = snapshot_engine.compare_snapshots(snapshot, previous)
    current_model = repo.store_wallet_snapshot(
        wallet_address=wallet_address,
        raw_json=snapshot.raw_json,
        collection_run_id=run_id,
        local_received_ts=snapshot.local_received_ts,
        exchange_ts=snapshot.exchange_ts,
        positions=snapshot.positions,
        open_orders=snapshot.open_orders,
        frontend_open_orders=snapshot.frontend_open_orders,
        fills=snapshot.fills,
        all_mids=snapshot.all_mids,
        source=source,
        stopped_reason=stopped_reason,
        errors=snapshot.errors + comparison.errors,
    )
    session.flush()
    current_model.summary = comparison.summary()
    comparison.current_snapshot_id = current_model.id
    if previous_model:
        comparison.previous_snapshot_id = previous_model.id
    for delta in comparison.deltas:
        delta.snapshot_id = current_model.id
    if comparison.deltas:
        repo.store_position_deltas(comparison.deltas)
    if echo_func:
        echo_func(f"snapshot {wallet_address}: {comparison.summary()}")
        for warning in comparison.warnings:
            echo_func(f"  warning: {warning}")


def _positions_payload(session: Session, wallet_address: str, raw_event: RawEvent | None) -> list[dict[str, Any]]:
    payload = raw_event.response_payload_json if raw_event else None
    if isinstance(payload, dict):
        asset_positions = payload.get("assetPositions")
        if isinstance(asset_positions, list):
            return [row for row in asset_positions if isinstance(row, dict)]
    positions = session.query(Position).filter(Position.wallet_address == wallet_address).all()
    return [
        {
            "coin": row.coin,
            "szi": row.size,
            "entryPx": row.entry_price or row.entry_px_estimated,
            "raw": row.raw_json,
        }
        for row in positions
    ]
