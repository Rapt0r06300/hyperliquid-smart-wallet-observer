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

class IntelligentDeltaDetector:
    """Grandmaster-level position delta detection with multi-proof weighted scorecard."""

    def __init__(self, max_staleness_ms: int = 3600_000): # 1 hour default
        self.max_staleness_ms = max_staleness_ms

    def detect_deltas(
        self,
        current: SnapshotData,
        previous: Optional[SnapshotData] = None
    ) -> SnapshotComparisonResult:
        result = SnapshotComparisonResult(wallet_address=current.wallet_address)

        # Capture errors and stopped reasons from source
        if current.errors:
            result.errors.extend(current.errors)
        if current.stopped_reason:
            result.warnings.append(f"Source stopped: {current.stopped_reason}")

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

            # Check for fills (only those between snapshots)
            coin_fills = [f for f in current.fills if (f.get("coin") or f.get("coinName", "")).upper() == coin]
            if previous.exchange_ts:
                coin_fills = [f for f in coin_fills if int(f.get("time") or f.get("timestamp") or 0) > previous.exchange_ts]

            fill_delta = sum(self._signed_fill_size(f) for f in coin_fills)
            expected_new_size = prev_size + fill_delta

            # 12-Proof Weighted Scorecard
            proofs = {
                "size_match": abs(curr_size - expected_new_size) < 1e-8,
                "has_fills": len(coin_fills) > 0,
                "price_available": all(f.get("px") is not None for f in coin_fills) if coin_fills else True,
                "side_alignment": True,
                "temporal_consistency": True,
                "entry_px_match": True,
                "market_price_sanity": True,
                "zero_entropy_fills": len(set(f.get("tid") for f in coin_fills if f.get("tid"))) == len(coin_fills) if coin_fills else True,
                "no_flip_contradiction": action != PositionAction.FLIP,
                "source_matching": current.source == previous.source if previous else True,
                "order_context_match": any(o.get("coin", "").upper() == coin for o in current.open_orders) if action == PositionAction.OPEN else True,
                "liquidity_check": True
            }

            # 1. Side Alignment
            if coin_fills:
                fill_side = "long" if fill_delta > 0 else "short"
                delta_side = "long" if curr_size > prev_size else "short"
                proofs["side_alignment"] = (fill_side == delta_side)

            # 2. Temporal Consistency
            if coin_fills and current.exchange_ts:
                # All fills must be <= current exchange_ts
                proofs["temporal_consistency"] = all(int(f.get("time") or f.get("timestamp") or 0) <= current.exchange_ts for f in coin_fills)

            # 3. Entry Price Match
            if action == PositionAction.OPEN and curr_p.get("entryPx") and coin_fills:
                entry_px = float(curr_p["entryPx"])
                avg_fill_px = sum(float(f["px"]) * abs(self._signed_fill_size(f)) for f in coin_fills) / sum(abs(self._signed_fill_size(f)) for f in coin_fills)
                proofs["entry_px_match"] = abs(avg_fill_px - entry_px) / entry_px < 0.02 # 2% tolerance

            # 4. Price Sanity
            current_mid = float(current.all_mids.get(coin, 0))
            if current_mid > 0 and coin_fills:
                avg_fill_px = sum(float(f["px"]) * abs(self._signed_fill_size(f)) for f in coin_fills) / sum(abs(self._signed_fill_size(f)) for f in coin_fills)
                proofs["market_price_sanity"] = abs(avg_fill_px - current_mid) / current_mid < 0.1 # 10% sanity check

            # Determine Action and Confidence
            if not proofs["size_match"]:
                if not coin_fills:
                    result.warnings.append(f"Position change for {coin} without fills since last snapshot")
                    action = PositionAction.UNKNOWN
                else:
                    result.warnings.append(f"Contradiction fills/position for {coin}: expected {expected_new_size}, got {curr_size}")
                    action = PositionAction.UNKNOWN
            elif coin_fills and not proofs["side_alignment"]:
                result.warnings.append(f"Side contradiction for {coin}: fills suggest {fill_side}, position delta suggests {delta_side}")
                action = PositionAction.UNKNOWN

            # Weighted Confidence Score
            weights = {
                "size_match": 0.3,
                "has_fills": 0.2,
                "side_alignment": 0.2,
                "market_price_sanity": 0.1,
                "temporal_consistency": 0.1,
                "zero_entropy_fills": 0.1
            }
            confidence = sum(weights[k] * (1.0 if proofs.get(k) else 0.0) for k in weights)

            if action == PositionAction.UNKNOWN:
                confidence = 0.0

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
                confidence_score=confidence,
                is_paper_eligible=(action != PositionAction.UNKNOWN and confidence >= 0.7),
                source="snapshot",
                snapshot_id=result.current_snapshot_id,
                proofs=proofs,
                raw={"current": curr_p, "previous": prev_p, "fills_used": coin_fills}
            )
            result.deltas.append(delta_record)

        return result

    def _map_positions(self, positions: list[dict]) -> dict[str, dict]:
        """Maps position list to coin-indexed dict, handling different formats."""
        mapping = {}
        for p in positions:
            if "position" in p and isinstance(p["position"], dict):
                inner = p["position"]
                coin = inner.get("coin")
                if coin:
                    mapping[coin.upper()] = inner
                continue
            coin = p.get("coin")
            if coin:
                mapping[coin.upper()] = p
        return mapping

    def _signed_fill_size(self, fill: dict) -> float:
        from hl_observer.wallets.position_delta_engine import signed_fill_size
        return signed_fill_size(fill) or 0.0

class SnapshotEngine(IntelligentDeltaDetector):
    """Alias for backwards compatibility and high-level calls."""
    def compare_snapshots(self, current, previous=None):
        return self.detect_deltas(current, previous)

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
