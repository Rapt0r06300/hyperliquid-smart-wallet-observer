from __future__ import annotations

from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
from typing import Any
import json

from hyper_smart_observer.hyperliquid_client.models import Fill, PositionSnapshot
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address


class NormalizationError(ValueError):
    """Raised when a read-only Hyperliquid payload lacks required fields."""


def normalize_user_fill(raw_fill: dict[str, Any], wallet_address: str) -> Fill:
    wallet = normalize_wallet_address(wallet_address)
    coin = _required_str(raw_fill, "coin")
    side = str(raw_fill.get("side") or raw_fill.get("dir") or "").strip()
    if not side:
        raise NormalizationError("fill side/dir is required")
    price = _required_float(raw_fill, "px", "price")
    size = _required_float(raw_fill, "sz", "size")
    fee = _optional_float(raw_fill.get("fee"), default=0.0)
    closed_pnl = _optional_float(
        raw_fill.get("closedPnl") if "closedPnl" in raw_fill else raw_fill.get("closed_pnl"),
        default=None,
    )
    start_position = _optional_float(
        raw_fill.get("startPosition") if "startPosition" in raw_fill else raw_fill.get("start_position"),
        default=None,
    )
    timestamp_ms = _required_int(raw_fill, "time", "timestamp")
    raw_id = _first_present(raw_fill, "hash", "oid", "tid")
    return Fill(
        wallet_address=wallet,
        coin=coin.upper(),
        side=side,
        price=price,
        size=size,
        fee=fee,
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        raw_id=str(raw_id) if raw_id not in (None, "") else None,
        source="hyperliquid_info",
        closed_pnl=closed_pnl,
        action_type=_classify_dir(side),
        start_position=start_position,
        fee_token=str(raw_fill.get("feeToken")) if raw_fill.get("feeToken") not in (None, "") else None,
        raw_json=json.dumps(raw_fill, sort_keys=True),
    )


def normalize_position_snapshot(raw_position: dict[str, Any], wallet_address: str) -> PositionSnapshot:
    wallet = normalize_wallet_address(wallet_address)
    position = raw_position.get("position") if "position" in raw_position else raw_position
    if not isinstance(position, dict):
        raise NormalizationError("position payload must be an object")
    coin = _required_str(position, "coin")
    size = _required_float(position, "szi", "size")
    leverage_value = position.get("leverage")
    if isinstance(leverage_value, dict):
        leverage = _optional_float(leverage_value.get("value"), default=None)
    else:
        leverage = _optional_float(leverage_value, default=None)
    return PositionSnapshot(
        wallet_address=wallet,
        coin=coin.upper(),
        size=size,
        entry_price=_optional_float(position.get("entryPx") or position.get("entry_price"), default=None),
        mark_price=_optional_float(position.get("markPx") or position.get("mark_price"), default=None),
        unrealized_pnl=_optional_float(
            position.get("unrealizedPnl") or position.get("unrealized_pnl"),
            default=None,
        ),
        leverage=leverage,
        timestamp=datetime.now(UTC),
    )


def _required_str(payload: dict[str, Any], *keys: str) -> str:
    value = _first_present(payload, *keys)
    if value in (None, ""):
        raise NormalizationError(f"required field missing: {'/'.join(keys)}")
    return str(value)


def _required_float(payload: dict[str, Any], *keys: str) -> float:
    value = _first_present(payload, *keys)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"required numeric field missing: {'/'.join(keys)}") from exc


def _required_int(payload: dict[str, Any], *keys: str) -> int:
    value = _first_present(payload, *keys)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"required integer field missing: {'/'.join(keys)}") from exc


def _optional_float(value: Any, *, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _classify_dir(direction: str) -> str:
    text = direction.strip().lower()
    if "open" in text and "long" in text:
        return "OPEN_LONG"
    if "open" in text and "short" in text:
        return "OPEN_SHORT"
    if "close" in text and "long" in text:
        return "CLOSE_LONG"
    if "close" in text and "short" in text:
        return "CLOSE_SHORT"
    if "long" in text:
        return "INCREASE_LONG"
    if "short" in text:
        return "INCREASE_SHORT"
    return "UNKNOWN"
