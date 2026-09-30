from __future__ import annotations

from datetime import datetime

from hyper_smart_observer.copy_mode.copy_models import DeltaAction, FillView, LeaderDelta, PositionView, stable_hash, utc_now


def classify_position_delta(previous_size: float | None, current_size: float | None) -> tuple[DeltaAction, list[str]]:
    warnings: list[str] = []
    if previous_size is None or current_size is None:
        return DeltaAction.UNKNOWN, ["missing_position_size"]
    old = float(previous_size)
    new = float(current_size)
    if old == 0 and new > 0:
        return DeltaAction.OPEN_LONG, warnings
    if old == 0 and new < 0:
        return DeltaAction.OPEN_SHORT, warnings
    if old > 0 and new > old:
        return DeltaAction.INCREASE, warnings
    if old < 0 and abs(new) > abs(old) and new < 0:
        return DeltaAction.INCREASE, warnings
    if old > 0 and 0 < new < old:
        return DeltaAction.REDUCE, warnings
    if old < 0 and old < new < 0:
        return DeltaAction.REDUCE, warnings
    if old > 0 and new == 0:
        return DeltaAction.CLOSE_LONG, warnings
    if old < 0 and new == 0:
        return DeltaAction.CLOSE_SHORT, warnings
    if (old > 0 and new < 0) or (old < 0 and new > 0):
        return DeltaAction.UNKNOWN, ["flip_detected_batch1_unknown"]
    return DeltaAction.UNKNOWN, ["no_copyable_position_change"]


def classify_fill_delta(fill: FillView, current_position_size: float | None = None) -> tuple[DeltaAction, list[str]]:
    warnings: list[str] = []
    direction = (fill.direction or "").strip().lower().replace("_", " ")
    start_position = fill.start_position
    if not direction:
        return DeltaAction.UNKNOWN, ["missing_fill_dir"]
    if "open long" in direction:
        if start_position is None:
            return DeltaAction.UNKNOWN, ["missing_start_position"]
        return (DeltaAction.OPEN_LONG if start_position == 0 else DeltaAction.ADD), warnings
    if "open short" in direction:
        if start_position is None:
            return DeltaAction.UNKNOWN, ["missing_start_position"]
        return (DeltaAction.OPEN_SHORT if start_position == 0 else DeltaAction.ADD), warnings
    if "close long" in direction:
        if current_position_size is None:
            return DeltaAction.UNKNOWN, ["missing_current_position_for_close"]
        return (DeltaAction.CLOSE_LONG if current_position_size == 0 else DeltaAction.REDUCE), warnings
    if "close short" in direction:
        if current_position_size is None:
            return DeltaAction.UNKNOWN, ["missing_current_position_for_close"]
        return (DeltaAction.CLOSE_SHORT if current_position_size == 0 else DeltaAction.REDUCE), warnings
    return DeltaAction.UNKNOWN, ["unknown_fill_dir"]


def diff_position_snapshots(
    previous: list[PositionView],
    current: list[PositionView],
    *,
    observed_at: datetime | None = None,
    source_snapshot_id: str | None = None,
    collection_run_id: str | None = None,
) -> list[LeaderDelta]:
    observed_at = observed_at or utc_now()
    previous_map = {(item.wallet_address.lower(), item.coin.upper()): item for item in previous}
    current_map = {(item.wallet_address.lower(), item.coin.upper()): item for item in current}
    keys = sorted(set(previous_map) | set(current_map))
    deltas: list[LeaderDelta] = []
    for key in keys:
        before = previous_map.get(key)
        after = current_map.get(key)
        previous_size = before.signed_size if before else 0.0
        current_size = after.signed_size if after else 0.0
        action, warnings = classify_position_delta(previous_size, current_size)
        if action == DeltaAction.UNKNOWN and "no_copyable_position_change" in warnings:
            continue
        wallet, coin = key
        raw_hash = stable_hash(f"{wallet}:{coin}:{previous_size}:{current_size}:{observed_at.isoformat()}")
        deltas.append(
            LeaderDelta(
                delta_id=f"delta:{raw_hash[:24]}",
                leader_wallet=wallet,
                coin=coin,
                action_type=action,
                observed_at=observed_at,
                previous_size=previous_size,
                current_size=current_size,
                leader_reference_price=(after or before).mark_price if (after or before) else None,
                raw_event_hash=raw_hash,
                source_snapshot_id=source_snapshot_id,
                collection_run_id=collection_run_id,
                warnings=warnings,
            )
        )
    return deltas
