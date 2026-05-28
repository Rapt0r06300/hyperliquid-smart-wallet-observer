from __future__ import annotations

import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from hl_observer.storage.models import WalletSnapshot, PositionDeltaModel
from hl_observer.wallets.position_delta_engine import (
    PositionSide,
    PositionAction,
    PositionDeltaRecord,
    position_side,
    classify_action,
)
from hl_observer.utils.time import now_ms

logger = logging.getLogger(__name__)

class SnapshotData(BaseModel):
    wallet_address: str
    collection_run_id: Optional[int] = None
    local_received_ts: int
    exchange_ts: Optional[int] = None
    positions: list[dict] = Field(default_factory=list)
    open_orders: list[dict] = Field(default_factory=list)
    frontend_open_orders: list[dict] = Field(default_factory=list)
    fills: list[dict] = Field(default_factory=list)
    all_mids: dict[str, str] = Field(default_factory=dict)
    source: Optional[str] = None
    stopped_reason: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
    raw_json: dict = Field(default_factory=dict)

class SnapshotComparisonResult(BaseModel):
    wallet_address: str
    is_baseline: bool = False
    deltas: list[PositionDeltaRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: Optional[str] = None
    previous_snapshot_id: Optional[int] = None
    current_snapshot_id: Optional[int] = None
    time_gap_ms: Optional[int] = None

    def summary(self) -> str:
        if self.refused:
            return f"REFUSED: {self.refusal_reason}"
        if self.is_baseline:
            return "BASELINE: First observation recorded"

        parts = [f"Deltas: {len(self.deltas)}"]
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        if self.time_gap_ms:
            parts.append(f"Gap: {self.time_gap_ms}ms")
        return "; ".join(parts)

class SnapshotEngine:
    def __init__(self, max_staleness_ms: int = 3600_000): # 1 hour default
        self.max_staleness_ms = max_staleness_ms

    def compare_snapshots(
        self,
        current: SnapshotData,
        previous: Optional[SnapshotData] = None
    ) -> SnapshotComparisonResult:
        result = SnapshotComparisonResult(wallet_address=current.wallet_address)

        if not previous:
            result.is_baseline = True
            logger.info(f"Baseline snapshot for {current.wallet_address}")
            return result

        # Check staleness
        if current.exchange_ts and previous.exchange_ts:
            age_ms = current.exchange_ts - previous.exchange_ts
            result.time_gap_ms = age_ms
            if age_ms > self.max_staleness_ms:
                result.refused = True
                result.refusal_reason = f"Snapshot too old: {age_ms}ms > {self.max_staleness_ms}ms"
                return result

        if not current.all_mids:
            result.warnings.append("Missing allMids in current snapshot")

        # Extract positions for easier comparison
        curr_pos_map = self._map_positions(current.positions)
        prev_pos_map = self._map_positions(previous.positions)

        all_coins = set(curr_pos_map.keys()) | set(prev_pos_map.keys())

        for coin in all_coins:
            curr_p = curr_pos_map.get(coin, {})
            prev_p = prev_pos_map.get(coin, {})

            curr_size = float(curr_p.get("szi", 0.0))
            prev_size = float(prev_p.get("szi", 0.0))

            if curr_size == prev_size:
                continue

            # Delta detected
            action = classify_action(prev_size, curr_size)

            # Check for contradiction with fills (only those between snapshots)
            coin_fills = [f for f in current.fills if (f.get("coin") or f.get("coinName", "")).upper() == coin]
            if previous.exchange_ts:
                coin_fills = [f for f in coin_fills if int(f.get("time") or f.get("timestamp") or 0) > previous.exchange_ts]

            fill_delta = sum(self._signed_fill_size(f) for f in coin_fills)

            expected_new_size = prev_size + fill_delta
            # Allow for some floating point tolerance
            if abs(curr_size - expected_new_size) > 1e-8:
                if not coin_fills:
                    result.warnings.append(f"Position change for {coin} without fills since last snapshot")
                    action = PositionAction.UNKNOWN
                else:
                    result.warnings.append(f"Contradiction fills/position for {coin}: expected {expected_new_size}, got {curr_size}")
                    action = PositionAction.UNKNOWN

            delta_record = PositionDeltaRecord(
                wallet_address=current.wallet_address,
                coin=coin,
                previous_side=position_side(prev_size),
                new_side=position_side(curr_size),
                previous_size=prev_size,
                new_size=curr_size,
                delta_size=curr_size - prev_size,
                action=action,
                exchange_ts=current.exchange_ts,
                confidence_score=1.0 if action != PositionAction.UNKNOWN else 0.2,
                source="snapshot",
                raw={"current": curr_p, "previous": prev_p, "fills_used": coin_fills}
            )
            result.deltas.append(delta_record)

        return result

    def _map_positions(self, positions: list[dict]) -> dict[str, dict]:
        """Maps position list to coin-indexed dict, handling different formats."""
        mapping = {}
        for p in positions:
            # Handle clearinghouseState format: {"position": {"coin": "BTC", "szi": "1.0", ...}}
            if "position" in p and isinstance(p["position"], dict):
                inner = p["position"]
                coin = inner.get("coin")
                if coin:
                    mapping[coin.upper()] = inner
                continue

            # Handle direct position format: {"coin": "BTC", "szi": "1.0", ...}
            coin = p.get("coin")
            if coin:
                mapping[coin.upper()] = p
        return mapping

    def _signed_fill_size(self, fill: dict) -> float:
        from hl_observer.wallets.position_delta_engine import signed_fill_size
        return signed_fill_size(fill) or 0.0

    @staticmethod
    def from_model(model: WalletSnapshot) -> SnapshotData:
        return SnapshotData(
            wallet_address=model.wallet_address,
            collection_run_id=model.collection_run_id,
            local_received_ts=model.local_received_ts or 0,
            exchange_ts=model.exchange_ts,
            positions=model.positions_json or [],
            open_orders=model.open_orders_json or [],
            frontend_open_orders=model.frontend_open_orders_json or [],
            fills=model.fills_json or [],
            all_mids=model.all_mids_json or {},
            source=model.source,
            stopped_reason=model.stopped_reason,
            errors=model.errors_json or [],
            raw_json=model.raw_json or {},
        )
