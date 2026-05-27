from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hyper_smart_observer.explorer_observer.explorer_models import ExplorerActionType, ExplorerEvent
from hyper_smart_observer.hyperliquid_client.validation import is_valid_wallet_address


def normalize_explorer_event(raw: dict[str, Any], *, source: str = "manual_import") -> ExplorerEvent:
    warnings: list[str] = []
    user = _first(raw, "user", "wallet", "address")
    if user is not None and not is_valid_wallet_address(str(user)):
        warnings.append("full wallet address missing or truncated; event cannot create a wallet candidate")
        user = None
    action = classify_explorer_action(str(_first(raw, "action", "action_type", "dir") or ""))
    if action == ExplorerActionType.UNKNOWN:
        warnings.append("ambiguous explorer action classified as UNKNOWN")
    price = _float(_first(raw, "price", "px"))
    size = _float(_first(raw, "size", "sz"))
    notional = _float(_first(raw, "notional", "value_usdc"))
    if notional is None and price is not None and size is not None:
        notional = abs(price * size)
    return ExplorerEvent(
        event_id=str(_first(raw, "event_id", "id") or uuid4()),
        source=source,
        block_time=_datetime(_first(raw, "block_time", "timestamp", "time")),
        tx_hash=_string(_first(raw, "tx_hash", "hash")),
        user=_string(user),
        action_type=action,
        coin=_upper(_first(raw, "coin", "asset")),
        side=_upper(_first(raw, "side")),
        size=size,
        price=price,
        notional=notional,
        closed_pnl=_float(_first(raw, "closed_pnl", "closedPnl")),
        fee=_float(_first(raw, "fee")),
        raw_json=json.dumps(raw, sort_keys=True),
        confidence=0.8 if user else 0.3,
        warnings=warnings,
    )


def classify_explorer_action(value: str) -> ExplorerActionType:
    text = value.lower()
    if "open" in text and "long" in text:
        return ExplorerActionType.OPEN_LONG
    if "open" in text and "short" in text:
        return ExplorerActionType.OPEN_SHORT
    if "close" in text and "long" in text:
        return ExplorerActionType.CLOSE_LONG
    if "close" in text and "short" in text:
        return ExplorerActionType.CLOSE_SHORT
    if "reduce" in text and "long" in text:
        return ExplorerActionType.REDUCE_LONG
    if "reduce" in text and "short" in text:
        return ExplorerActionType.REDUCE_SHORT
    if "increase" in text and "long" in text:
        return ExplorerActionType.INCREASE_LONG
    if "increase" in text and "short" in text:
        return ExplorerActionType.INCREASE_SHORT
    if "liquidation" in text:
        return ExplorerActionType.LIQUIDATION
    if "funding" in text:
        return ExplorerActionType.FUNDING
    if "withdraw" in text:
        return ExplorerActionType.WITHDRAWAL
    if "deposit" in text:
        return ExplorerActionType.DEPOSIT
    if "transfer" in text:
        return ExplorerActionType.TRANSFER
    if "cancel" in text:
        return ExplorerActionType.ORDER_CANCEL
    return ExplorerActionType.UNKNOWN


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    try:
        if value in (None, ""):
            return None
        numeric = int(value)
        if numeric > 10_000_000_000:
            return datetime.fromtimestamp(numeric / 1000, tz=UTC)
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _string(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _upper(value: Any) -> str | None:
    text = _string(value)
    return text.upper() if text else None
