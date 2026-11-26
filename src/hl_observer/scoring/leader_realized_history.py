"""Rebuild verified, closed leader position cycles from persisted position deltas.

Only public-fill-derived, paper-eligible observations with a stable event identity,
timestamp, price, size transition and matching fill size contribute. Partial closes
are accumulated and a return is emitted only after the position is fully closed.
This is a historical quality input, not a profitability certificate.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import func

ENTRY_ACTIONS = {"OPEN", "ADD", "OPEN_LONG", "OPEN_SHORT", "INCREASE"}
PARTIAL_EXIT_ACTIONS = {"REDUCE"}
FULL_EXIT_ACTIONS = {"CLOSE", "CLOSE_LONG", "CLOSE_SHORT"}
SUPPORTED_SOURCES = {"fills", "user_fills"}
SIZE_ABS_TOLERANCE = 1e-9
SIZE_REL_TOLERANCE = 1e-6


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _event_identity(delta: dict) -> str:
    for name in ("event_identity", "delta_hash", "fill_id", "source_event_id"):
        value = delta.get(name)
        if value is not None and str(value).strip():
            return f"{name}:{value}"
    return ""


def _validated_event(delta: dict) -> dict | None:
    wallet = str(delta.get("wallet") or "").strip().casefold()
    coin = str(delta.get("coin") or "").strip().upper()
    action = str(delta.get("action") or "").strip().upper()
    identity = _event_identity(delta)
    source = str(delta.get("source") or "").strip().casefold()
    proofs = delta.get("proofs") or delta.get("proofs_json")
    verified_snapshot = source == "snapshot" and isinstance(proofs, dict) and all(
        proofs.get(name) is True
        for name in ("has_fills", "size_match", "temporal_consistency", "price_from_fill")
    )
    verified_fill_source = source in SUPPORTED_SOURCES or source.startswith("hyperliquid_ws:userfills")
    if (
        not wallet
        or not coin
        or not identity
        or not (verified_fill_source or verified_snapshot)
        or delta.get("is_paper_eligible") is not True
    ):
        return None

    confidence = _finite_float(delta.get("confidence_score"))
    price = _finite_float(delta.get("price"))
    previous = _finite_float(delta.get("previous_size"))
    raw_new_size = delta.get("new_size")
    if raw_new_size is None:
        raw_new_size = delta.get("current_size")
    new = _finite_float(raw_new_size)
    fill_size = _finite_float(delta.get("fill_size"))
    raw_ts = _finite_float(delta.get("exchange_ts"))
    raw_sequence = _finite_float(delta.get("source_sequence"))
    source_sequence = (
        int(raw_sequence)
        if raw_sequence is not None and raw_sequence >= 0 and raw_sequence.is_integer()
        else None
    )
    if (
        confidence is None
        or confidence < 0.7
        or price is None
        or price <= 0
        or previous is None
        or new is None
        or fill_size is None
        or fill_size <= 0
        or raw_ts is None
        or raw_ts <= 0
        or not raw_ts.is_integer()
    ):
        return None
    delta_size = abs(new - previous)
    if delta_size <= SIZE_ABS_TOLERANCE or not math.isclose(
        fill_size,
        delta_size,
        rel_tol=SIZE_REL_TOLERANCE,
        abs_tol=SIZE_ABS_TOLERANCE,
    ):
        return None

    return {
        "wallet": wallet,
        "coin": coin,
        "action": action,
        "identity": identity,
        "timestamp": int(raw_ts),
        "source_sequence": source_sequence,
        "fill_id": delta.get("fill_id"),
        "source_event_id": delta.get("source_event_id"),
        "previous": previous,
        "new": new,
        "price": price,
        "fill_size": fill_size,
        "key": (wallet, coin),
        "fingerprint": (wallet, coin, action, int(raw_ts), previous, new, price, fill_size),
    }


def _approx_equal(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=SIZE_REL_TOLERANCE, abs_tol=SIZE_ABS_TOLERANCE)


def round_trip_moves(deltas: Iterable[dict]) -> dict[str, list[float]]:
    """Return gross realized bps for verified, fully closed leader cycles.

    Rows must carry ``wallet``, ``coin``, ``action``, signed ``previous_size`` and
    ``new_size`` (or ``current_size``), ``fill_size``, ``price``, ``exchange_ts``,
    stable event identity, ``source``, ``confidence_score`` and an exact true
    ``is_paper_eligible`` flag. The caller's economic gate applies replay costs.
    """
    events: list[dict] = []
    barriers: list[dict] = []
    identities: dict[tuple[str, str], list[dict]] = defaultdict(list)
    out: dict[str, list[float]] = defaultdict(list)

    for row in deltas:
        if not isinstance(row, dict):
            continue
        event = _validated_event(row)
        if event is None:
            wallet = str(row.get("wallet") or "").strip().casefold()
            coin = str(row.get("coin") or "").strip().upper()
            timestamp = _finite_float(row.get("exchange_ts"))
            if wallet and coin and timestamp is not None and timestamp > 0 and timestamp.is_integer():
                barriers.append({
                    "kind": "INVALID",
                    "key": (wallet, coin),
                    "timestamp": int(timestamp),
                    "identity": "invalid-event",
                })
            continue
        identity_key = (event["wallet"], event["identity"])
        identities[identity_key].append(event)

    for observations in identities.values():
        fingerprints = {item["fingerprint"] for item in observations}
        if len(fingerprints) == 1:
            events.append(observations[0])
            continue
        # A reused identity with conflicting payloads invalidates both observations.
        for item in observations:
            barriers.append({
                "kind": "INVALID",
                "key": item["key"],
                "timestamp": item["timestamp"],
                "identity": "conflicting-identity",
            })
    events.extend(barriers)

    # Millisecond timestamps do not order multiple fills within that millisecond.
    # A content hash is an identity, not a causal sequence; reject the affected
    # wallet/coin cycle unless persistence supplied a unique sequence number.
    by_key_timestamp: dict[tuple[tuple[str, str], int], list[dict]] = defaultdict(list)
    for event in events:
        by_key_timestamp[(event["key"], event["timestamp"])].append(event)
    ordered_events: list[dict] = []
    for (key, timestamp), group in by_key_timestamp.items():
        sequences = [event.get("source_sequence") for event in group]
        if len(group) > 1 and (
            any(sequence is None for sequence in sequences)
            or len(set(sequences)) != len(sequences)
        ):
            ordered_events.append({
                "kind": "INVALID",
                "key": key,
                "timestamp": timestamp,
                "identity": "ambiguous-same-timestamp",
            })
        else:
            ordered_events.extend(group)
    events = ordered_events

    def order_key(event: dict) -> tuple:
        if event.get("kind") == "INVALID":
            return (event["timestamp"], 0, math.inf, math.inf, event["identity"])
        source_sequence = event.get("source_sequence")
        fill_id = _finite_float(event["fill_id"])
        source_event_id = _finite_float(event["source_event_id"])
        return (
            event["timestamp"],
            1,
            source_sequence if source_sequence is not None else math.inf,
            fill_id if fill_id is not None else math.inf,
            source_event_id if source_event_id is not None else math.inf,
            event["identity"],
        )

    events.sort(key=order_key)
    positions: dict[tuple[str, str], dict] = {}
    last_timestamp: dict[tuple[str, str], int] = {}

    for event in events:
        key = event["key"]
        if event.get("kind") == "INVALID":
            positions.pop(key, None)
            last_timestamp[key] = max(last_timestamp.get(key, 0), event["timestamp"])
            continue
        wallet = event["wallet"]
        action = event["action"]
        previous = event["previous"]
        new = event["new"]
        price = event["price"]
        timestamp = event["timestamp"]
        position = positions.get(key)

        prior_ts = last_timestamp.get(key)
        last_timestamp[key] = timestamp
        if prior_ts is not None and timestamp < prior_ts:
            positions.pop(key, None)
            continue

        if action in {"FLIP", "UNKNOWN", "LIQUIDATION"}:
            positions.pop(key, None)
            continue

        if action in {"OPEN", "OPEN_LONG", "OPEN_SHORT"}:
            alias_side_mismatch = (
                (action == "OPEN_LONG" and new < 0)
                or (action == "OPEN_SHORT" and new > 0)
            )
            if not _approx_equal(previous, 0.0) or _approx_equal(new, 0.0) or alias_side_mismatch:
                positions.pop(key, None)
                continue
            positions[key] = {
                "sign": 1.0 if new > 0 else -1.0,
                "quantity": abs(new),
                "average_entry": price,
                "entry_notional": abs(new) * price,
                "realized_pnl": 0.0,
            }
            continue

        if action not in ENTRY_ACTIONS | PARTIAL_EXIT_ACTIONS | FULL_EXIT_ACTIONS or position is None:
            positions.pop(key, None)
            continue
        if not _approx_equal(previous, position["sign"] * position["quantity"]):
            positions.pop(key, None)
            continue

        same_direction = new == 0.0 or (new > 0) == (position["sign"] > 0)
        if not same_direction:
            positions.pop(key, None)
            continue

        previous_quantity = position["quantity"]
        new_quantity = abs(new)
        if action in {"ADD", "INCREASE"}:
            added_quantity = new_quantity - previous_quantity
            if added_quantity <= SIZE_ABS_TOLERANCE:
                positions.pop(key, None)
                continue
            entry_notional = position["entry_notional"] + added_quantity * price
            position["average_entry"] = entry_notional / new_quantity
            position["entry_notional"] = entry_notional
            position["quantity"] = new_quantity
            continue

        if action == "REDUCE":
            closed_quantity = previous_quantity - new_quantity
            if closed_quantity <= SIZE_ABS_TOLERANCE or new_quantity <= SIZE_ABS_TOLERANCE:
                positions.pop(key, None)
                continue
            position["realized_pnl"] += (
                (price - position["average_entry"]) * position["sign"] * closed_quantity
            )
            position["quantity"] = new_quantity
            continue

        if action in FULL_EXIT_ACTIONS:
            alias_side_mismatch = (
                (action == "CLOSE_LONG" and previous < 0)
                or (action == "CLOSE_SHORT" and previous > 0)
            )
            if not _approx_equal(new, 0.0) or alias_side_mismatch:
                positions.pop(key, None)
                continue
            closed_quantity = previous_quantity
            position["realized_pnl"] += (
                (price - position["average_entry"]) * position["sign"] * closed_quantity
            )
            entry_notional = position["entry_notional"]
            if entry_notional > 0 and math.isfinite(entry_notional):
                move_bps = position["realized_pnl"] / entry_notional * 10_000.0
                if math.isfinite(move_bps):
                    out[wallet].append(move_bps)
            positions.pop(key, None)

    return dict(out)


def wallet_round_trip_moves_from_session(session, wallets, *, max_rows: int = 20_000) -> dict[str, list[float]]:
    """Load recent verified deltas with an equal per-wallet share of the row cap.

    A global newest-first LIMIT lets a few high-activity wallets starve every
    other candidate. Rank rows within each wallet first, then enforce the same
    total budget and restore deterministic chronological replay order.
    """
    row_budget = max(0, int(max_rows))
    address_by_key: dict[str, str] = {}
    for wallet in wallets:
        address = str(wallet or "").strip()
        if address:
            address_by_key.setdefault(address.casefold(), address)
    addrs = [address_by_key[key] for key in sorted(address_by_key)]
    if row_budget == 0 or not addrs:
        return {}
    try:
        from hl_observer.storage.models import PositionDeltaModel
    except Exception:
        return {}
    if len(addrs) > row_budget:
        addrs = addrs[:row_budget]
    per_wallet_budget = max(1, row_budget // len(addrs))
    ranked_ids = (
        session.query(
            PositionDeltaModel.id.label("id"),
            func.row_number()
            .over(
                partition_by=func.lower(PositionDeltaModel.wallet_address),
                order_by=(PositionDeltaModel.exchange_ts.desc(), PositionDeltaModel.id.desc()),
            )
            .label("wallet_row_number"),
        )
        .filter(PositionDeltaModel.wallet_address.in_(addrs))
        .subquery()
    )
    newest_rows = (
        session.query(PositionDeltaModel)
        .join(ranked_ids, PositionDeltaModel.id == ranked_ids.c.id)
        .filter(ranked_ids.c.wallet_row_number <= per_wallet_budget)
        .order_by(
            PositionDeltaModel.exchange_ts.desc(),
            PositionDeltaModel.id.desc(),
        )
        .limit(row_budget)
        .all()
    )
    rows = list(reversed(newest_rows))
    deltas = [
        {
            "wallet": row.wallet_address,
            "coin": row.coin,
            "action": row.action,
            "previous_size": row.previous_size,
            "new_size": row.new_size if row.new_size is not None else row.current_size,
            "fill_size": row.fill_size,
            "price": row.price,
            "exchange_ts": row.exchange_ts,
            "source_sequence": row.id,
            "fill_id": row.fill_id,
            "source_event_id": row.source_event_id,
            "delta_hash": row.delta_hash,
            "source": row.source,
            "confidence_score": row.confidence_score,
            "is_paper_eligible": row.is_paper_eligible,
        }
        for row in rows
    ]
    return round_trip_moves(deltas)


__all__ = ["round_trip_moves", "wallet_round_trip_moves_from_session"]
