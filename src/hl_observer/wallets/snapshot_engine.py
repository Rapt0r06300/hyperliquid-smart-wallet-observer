from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hl_observer.storage.models import WalletSnapshot
from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    PositionDeltaRecord,
    classify_action,
    position_side,
    signed_fill_size,
)


class SnapshotData(BaseModel):
    wallet_address: str
    collection_run_id: int | None = None
    local_received_ts: int
    exchange_ts: int | None = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    open_orders: list[dict[str, Any]] = Field(default_factory=list)
    frontend_open_orders: list[dict[str, Any]] = Field(default_factory=list)
    fills: list[dict[str, Any]] = Field(default_factory=list)
    all_mids: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    stopped_reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    raw_json: dict[str, Any] = Field(default_factory=dict)


class SnapshotComparisonResult(BaseModel):
    wallet_address: str
    is_baseline: bool = False
    deltas: list[PositionDeltaRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    previous_snapshot_id: int | None = None
    current_snapshot_id: int | None = None
    time_gap_ms: int | None = None

    def summary(self) -> str:
        if self.refused:
            return f"REFUSED: {self.refusal_reason}"
        if self.is_baseline:
            return "BASELINE: first observation recorded"
        return f"deltas={len(self.deltas)} warnings={len(self.warnings)}"


class SnapshotEngine:
    """Read-only snapshot comparator for leader positions.

    The engine refuses ambiguity: a position change without matching fills, a
    side contradiction, or a flip is classified as UNKNOWN and is not paper
    eligible.
    """

    def __init__(self, *, max_staleness_ms: int = 3_600_000) -> None:
        self.max_staleness_ms = max_staleness_ms

    def compare_snapshots(
        self,
        current: SnapshotData,
        previous: SnapshotData | None = None,
    ) -> SnapshotComparisonResult:
        result = SnapshotComparisonResult(wallet_address=current.wallet_address)
        result.errors.extend(current.errors)
        if current.stopped_reason:
            result.warnings.append(f"source_stopped:{current.stopped_reason}")
        if previous is None:
            result.is_baseline = True
            return result
        if current.exchange_ts is not None and previous.exchange_ts is not None:
            result.time_gap_ms = current.exchange_ts - previous.exchange_ts
            if result.time_gap_ms > self.max_staleness_ms:
                result.refused = True
                result.refusal_reason = "SNAPSHOT_TOO_STALE"
                return result
        if not current.all_mids:
            result.warnings.append("MISSING_ALL_MIDS")

        current_positions = _position_map(current.positions)
        previous_positions = _position_map(previous.positions)
        for coin in sorted(set(current_positions) | set(previous_positions)):
            current_payload = current_positions.get(coin, {})
            previous_payload = previous_positions.get(coin, {})
            current_size = _safe_float(current_payload.get("szi"), 0.0)
            previous_size = _safe_float(previous_payload.get("szi"), 0.0)
            if current_size == previous_size:
                continue

            fills = _fills_for_coin(current.fills, coin, after_ts=previous.exchange_ts)
            fill_delta = sum(signed_fill_size(fill) or 0.0 for fill in fills)
            expected_new_size = previous_size + fill_delta
            action = classify_action(previous_size, current_size)
            proofs = {
                "has_fills": bool(fills),
                "size_match": abs(current_size - expected_new_size) < 1e-8,
                "no_flip": action != PositionAction.FLIP,
                "price_available": all(_safe_float(fill.get("px")) is not None for fill in fills) if fills else False,
                "temporal_consistency": all(_safe_int(fill.get("time") or fill.get("timestamp")) is not None for fill in fills)
                if fills
                else False,
            }
            notes: list[str] = []
            if action == PositionAction.FLIP:
                notes.append("flip_classified_unknown")
                action = PositionAction.UNKNOWN
            if not proofs["has_fills"]:
                notes.append("position_change_without_matching_fills")
                action = PositionAction.UNKNOWN
                result.warnings.append(f"{coin}:POSITION_CHANGE_WITHOUT_FILLS")
            elif not proofs["size_match"]:
                notes.append("fills_position_size_mismatch")
                action = PositionAction.UNKNOWN
                result.warnings.append(f"{coin}:FILLS_POSITION_CONTRADICTION")
            confidence = 0.0 if action == PositionAction.UNKNOWN else _confidence_from_proofs(proofs)
            price = _weighted_fill_price(fills) or _safe_float(current.all_mids.get(coin))
            delta = PositionDeltaRecord(
                wallet_address=current.wallet_address,
                coin=coin,
                previous_side=position_side(previous_size),
                new_side=position_side(current_size),
                previous_size=previous_size,
                new_size=current_size,
                delta_size=current_size - previous_size,
                delta_notional_usdc=abs(current_size - previous_size) * price if price is not None else None,
                action=action,
                exchange_ts=current.exchange_ts,
                price=price,
                fill_size=abs(fill_delta) if fills else None,
                confidence_score=confidence,
                is_paper_eligible=action != PositionAction.UNKNOWN and confidence >= 0.7,
                proofs=proofs,
                source="snapshot",
                notes=notes,
                raw={"current": current_payload, "previous": previous_payload, "fills_used": fills},
            )
            result.deltas.append(delta)
        return result

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


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for payload in positions:
        if not isinstance(payload, dict):
            continue
        inner = payload.get("position") if isinstance(payload.get("position"), dict) else payload
        coin = inner.get("coin") if isinstance(inner, dict) else None
        if coin:
            mapped[str(coin).upper()] = inner
    return mapped


def _fills_for_coin(fills: list[dict[str, Any]], coin: str, *, after_ts: int | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fill in fills:
        if str(fill.get("coin") or fill.get("coinName") or "").upper() != coin:
            continue
        fill_ts = _safe_int(fill.get("time") or fill.get("timestamp")) or 0
        if after_ts is not None and fill_ts <= after_ts:
            continue
        out.append(fill)
    return sorted(out, key=lambda item: _safe_int(item.get("time") or item.get("timestamp")) or 0)


def _weighted_fill_price(fills: list[dict[str, Any]]) -> float | None:
    total_size = 0.0
    total_value = 0.0
    for fill in fills:
        price = _safe_float(fill.get("px") or fill.get("price"))
        size = abs(signed_fill_size(fill) or _safe_float(fill.get("sz") or fill.get("size"), 0.0))
        if price is None or size <= 0:
            continue
        total_size += size
        total_value += price * size
    if total_size <= 0:
        return None
    return total_value / total_size


def _confidence_from_proofs(proofs: dict[str, bool]) -> float:
    weights = {
        "has_fills": 0.25,
        "size_match": 0.35,
        "no_flip": 0.2,
        "price_available": 0.1,
        "temporal_consistency": 0.1,
    }
    return sum(weight for name, weight in weights.items() if proofs.get(name))


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
