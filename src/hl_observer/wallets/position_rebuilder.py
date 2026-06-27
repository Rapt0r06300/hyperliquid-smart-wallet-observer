from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    PositionDeltaRecord,
    PositionSide,
    build_position_delta_from_fill,
    fill_coin,
    fill_price,
    fill_size,
    fill_timestamp,
    position_side,
    start_position,
)


class RebuiltPosition(BaseModel):
    wallet_address: str
    coin: str
    side: PositionSide
    size: float
    entry_px_estimated: float | None = None
    last_px: float | None = None
    notional_usdc: float | None = None
    source: str = "user_fills"
    confidence_score: float = 0.0
    opened_at_ms: int | None = None
    updated_at_ms: int | None = None
    status: str = "INCOMPLETE"
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PositionRebuildResult(BaseModel):
    wallet_address: str
    positions: list[RebuiltPosition] = Field(default_factory=list)
    deltas: list[PositionDeltaRecord] = Field(default_factory=list)
    sorted_fills: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class _CoinState(BaseModel):
    size: float = 0.0
    entry_px_estimated: float | None = None
    opened_at_ms: int | None = None
    last_px: float | None = None
    updated_at_ms: int | None = None
    confidence_scores: list[float] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    last_raw: dict[str, Any] = Field(default_factory=dict)


def sort_fills_by_time(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(fills, key=fill_timestamp)


def rebuild_positions_from_fills(wallet_address: str, fills: list[dict[str, Any]]) -> PositionRebuildResult:
    sorted_fills = sort_fills_by_time(fills)
    states: dict[str, _CoinState] = {}
    deltas: list[PositionDeltaRecord] = []
    global_notes: list[str] = []

    for fill in sorted_fills:
        coin = fill_coin(fill)
        state = states.setdefault(coin, _CoinState())
        previous_size = start_position(fill)
        if previous_size is None:
            previous_size = state.size
        delta = build_position_delta_from_fill(wallet_address, fill, previous_size=previous_size)
        deltas.append(delta)
        state.confidence_scores.append(delta.confidence_score)
        state.notes.extend(delta.notes)
        state.last_raw = fill

        if delta.action == PositionAction.UNKNOWN:
            global_notes.extend(delta.notes)
            state.last_px = fill_price(fill) or state.last_px
            state.updated_at_ms = delta.exchange_ts or state.updated_at_ms
            continue

        old_size = state.size
        state.size = delta.new_size
        price = fill_price(fill)
        size = fill_size(fill) or 0.0
        if price is not None:
            state.last_px = price
        state.updated_at_ms = delta.exchange_ts or state.updated_at_ms

        if delta.action in {PositionAction.OPEN, PositionAction.FLIP}:
            state.opened_at_ms = delta.exchange_ts
            state.entry_px_estimated = price
        elif delta.action == PositionAction.ADD and price is not None and state.entry_px_estimated is not None:
            previous_abs = abs(old_size)
            added_abs = abs(size)
            denominator = previous_abs + added_abs
            if denominator > 0:
                state.entry_px_estimated = (
                    state.entry_px_estimated * previous_abs + price * added_abs
                ) / denominator
        elif delta.action == PositionAction.ADD and state.entry_px_estimated is None:
            state.entry_px_estimated = price
        elif delta.action == PositionAction.CLOSE:
            state.entry_px_estimated = None

    positions = [_position_from_state(wallet_address, coin, state) for coin, state in states.items()]
    confidence_values = [score for state in states.values() for score in state.confidence_scores]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    return PositionRebuildResult(
        wallet_address=wallet_address,
        positions=positions,
        deltas=deltas,
        sorted_fills=sorted_fills,
        confidence_score=confidence,
        notes=sorted(set(global_notes)),
    )


def _position_from_state(wallet_address: str, coin: str, state: _CoinState) -> RebuiltPosition:
    side = position_side(state.size)
    confidence = (
        sum(state.confidence_scores) / len(state.confidence_scores)
        if state.confidence_scores
        else 0.0
    )
    status = "OPEN" if side in {PositionSide.LONG, PositionSide.SHORT} else "CLOSED"
    if confidence < 0.5 or "direction_unclear" in state.notes:
        status = "INCOMPLETE"
    notional = abs(state.size) * state.last_px if state.last_px is not None else None
    return RebuiltPosition(
        wallet_address=wallet_address,
        coin=coin,
        side=side,
        size=state.size,
        entry_px_estimated=state.entry_px_estimated,
        last_px=state.last_px,
        notional_usdc=notional,
        confidence_score=confidence,
        opened_at_ms=state.opened_at_ms,
        updated_at_ms=state.updated_at_ms,
        status=status,
        notes=sorted(set(state.notes)),
        raw=state.last_raw,
    )
