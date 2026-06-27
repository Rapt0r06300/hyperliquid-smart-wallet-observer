from __future__ import annotations

from typing import Any

from hl_observer.storage.models import PositionDeltaModel


def copy_delta_action(row: PositionDeltaModel) -> str:
    raw = f"{row.delta_type or ''} {row.action or ''} {row.previous_side or ''} {row.new_side or ''} {row.side or ''}".lower()
    previous = (row.previous_side or "").lower()
    new = (row.new_side or row.side or "").lower()
    if "open" in raw:
        if "short" in raw or new == "short" or row.current_size < 0:
            return "OPEN_SHORT"
        if "long" in raw or new == "long" or row.current_size > 0:
            return "OPEN_LONG"
    if "add" in raw:
        return "ADD"
    if "increase" in raw:
        return "INCREASE"
    if "reduce" in raw:
        return "REDUCE"
    if "close" in raw:
        if "short" in raw or previous == "short" or row.previous_size < 0:
            return "CLOSE_SHORT"
        if "long" in raw or previous == "long" or row.previous_size > 0:
            return "CLOSE_LONG"
    return "UNKNOWN"


def copy_delta_direction(row: PositionDeltaModel, action: str | None = None) -> str | None:
    action = action or copy_delta_action(row)
    if action == "OPEN_LONG":
        return "LONG"
    if action == "OPEN_SHORT":
        return "SHORT"
    if action in {"ADD", "INCREASE"}:
        if row.current_size > 0 or (row.new_side or row.side or "").lower() == "long":
            return "LONG"
        if row.current_size < 0 or (row.new_side or row.side or "").lower() == "short":
            return "SHORT"
    if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
        if action == "CLOSE_LONG":
            return "LONG"
        if action == "CLOSE_SHORT":
            return "SHORT"
        if row.previous_size > 0 or (row.previous_side or "").lower() == "long":
            return "LONG"
        if row.previous_size < 0 or (row.previous_side or "").lower() == "short":
            return "SHORT"
    return None


def delta_event_time_ms(row: PositionDeltaModel) -> int:
    return int(row.detected_at_ms or row.exchange_ts or 0)


def build_position_consensus(
    rows: list[PositionDeltaModel],
    *,
    window_ms: int = 300_000,
    min_wallets: int = 2,
) -> list[dict[str, Any]]:
    entry_rows: list[dict[str, Any]] = []
    for row in rows:
        action = copy_delta_action(row)
        direction = copy_delta_direction(row, action)
        if direction is None or action not in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
            continue
        observed = delta_event_time_ms(row)
        if observed <= 0:
            continue
        entry_rows.append(
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "direction": direction,
                "action": action,
                "observed_at_ms": observed,
                "price": row.price,
                "notional_usdc": row.delta_notional_usdc,
            }
        )

    consensus: list[dict[str, Any]] = []
    keys = sorted({(row["coin"], row["direction"]) for row in entry_rows})
    for coin, direction in keys:
        group = sorted(
            [row for row in entry_rows if row["coin"] == coin and row["direction"] == direction],
            key=lambda item: item["observed_at_ms"],
        )
        best: list[dict[str, Any]] = []
        for index, row in enumerate(group):
            end_ms = row["observed_at_ms"] + window_ms
            candidate = [item for item in group[index:] if item["observed_at_ms"] <= end_ms]
            if len({item["wallet_address"].lower() for item in candidate}) > len(
                {item["wallet_address"].lower() for item in best}
            ):
                best = candidate
        wallets = sorted({item["wallet_address"].lower() for item in best})
        if len(wallets) < min_wallets:
            continue
        first_seen = min(item["observed_at_ms"] for item in best)
        last_seen = max(item["observed_at_ms"] for item in best)
        span_ratio = min(1.0, max(0.0, (last_seen - first_seen) / window_ms))
        wallet_count = len(wallets)
        crowding_risk = "HIGH" if wallet_count >= 4 else "MEDIUM" if wallet_count == 3 else "LOW"
        warnings = []
        if crowding_risk == "HIGH":
            warnings.append("crowding_risk_many_wallets_same_direction")
        consensus.append(
            {
                "coin": coin,
                "direction": direction,
                "wallet_count": wallet_count,
                "wallets": wallets,
                "first_seen_ms": first_seen,
                "last_seen_ms": last_seen,
                "window_seconds": int(window_ms / 1000),
                "consensus_score": round(min(100.0, 45.0 + wallet_count * 18.0 + (1.0 - span_ratio) * 20.0), 2),
                "crowding_risk": crowding_risk,
                "warnings": warnings,
                "research_only": True,
                "total_notional_usdc": sum(float(item["notional_usdc"] or 0.0) for item in best),
            }
        )
    return sorted(consensus, key=lambda item: (item["wallet_count"], item["consensus_score"]), reverse=True)
