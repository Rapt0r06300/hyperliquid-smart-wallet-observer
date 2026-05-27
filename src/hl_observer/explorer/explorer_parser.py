from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from hl_observer.explorer.explorer_models import ExplorerSourceStatus, ExplorerTransaction
from hl_observer.explorer.explorer_validation import validate_explorer_wallet_address
from hl_observer.wallets.leaderboard_validation import is_truncated_wallet_display

FULL_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
TRUNCATED_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{2,12}\.\.\.[a-fA-F0-9]{2,12}")
TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")
COIN_RE = re.compile(r"\b(BTC|ETH|SOL|HYPE|[A-Z0-9]{2,12})\b")


def parse_explorer_payload(payload: Any, *, source_url: str) -> tuple[list[ExplorerTransaction], int]:
    if isinstance(payload, list):
        return parse_explorer_records([item for item in payload if isinstance(item, dict)], source_url=source_url)
    if isinstance(payload, dict):
        if isinstance(payload.get("txs"), list):
            return parse_explorer_records(payload["txs"], source_url=source_url)
        if isinstance(payload.get("tx"), dict):
            return parse_explorer_records([payload["tx"]], source_url=source_url)
        block_details = payload.get("blockDetails")
        if isinstance(block_details, dict) and isinstance(block_details.get("txs"), list):
            return parse_explorer_records(block_details["txs"], source_url=source_url)
    text = _to_text(payload)
    full_addresses = list(dict.fromkeys(FULL_ADDRESS_RE.findall(text)))
    truncated_addresses = list(dict.fromkeys(TRUNCATED_ADDRESS_RE.findall(text)))
    tx_hashes = list(dict.fromkeys(TX_HASH_RE.findall(text)))
    transactions: list[ExplorerTransaction] = []

    if tx_hashes:
        for index, tx_hash in enumerate(tx_hashes):
            wallet = full_addresses[index % len(full_addresses)] if full_addresses else None
            transactions.append(_build_transaction(tx_hash, wallet, payload, source_url))
    elif full_addresses:
        for wallet in full_addresses:
            transactions.append(_build_transaction(None, wallet, payload, source_url))

    return transactions, len(truncated_addresses)


def parse_explorer_records(records: list[dict[str, Any]], *, source_url: str = "local_import") -> tuple[list[ExplorerTransaction], int]:
    transactions: list[ExplorerTransaction] = []
    truncated = 0
    for raw in records:
        address = raw.get("wallet_address") or raw.get("address") or raw.get("user")
        if isinstance(address, str) and is_truncated_wallet_display(address):
            truncated += 1
        tx = _build_transaction(
            str(raw.get("tx_hash") or raw.get("hash") or "") or None,
            str(address) if address is not None else None,
            raw,
            source_url,
        )
        tx.block = _to_int(raw.get("block") or raw.get("block_number"))
        tx.timestamp_ms = _to_int(raw.get("timestamp_ms") or raw.get("time"))
        action = raw.get("action")
        tx.action_type = _action_type(raw)
        tx.coin = _coin_hint(raw)
        tx.side = _side_hint(raw)
        tx.size = _size_hint(raw)
        tx.price = _price_hint(raw)
        tx.value_usdc = _to_float(raw.get("value_usdc") or raw.get("notional"))
        if isinstance(action, dict):
            tx.raw_payload["action_type"] = tx.action_type
            tx.raw_payload["asset_hint"] = tx.coin
        transactions.append(tx)
    return transactions, truncated


def _build_transaction(
    tx_hash: str | None,
    wallet_address: str | None,
    raw_payload: Any,
    source_url: str,
) -> ExplorerTransaction:
    ok, status = validate_explorer_wallet_address(wallet_address)
    normalized = wallet_address.lower() if ok and wallet_address else None
    payload = raw_payload if isinstance(raw_payload, dict) else {"payload": _to_text(raw_payload)[:5000]}
    return ExplorerTransaction(
        tx_hash=tx_hash if tx_hash and TX_HASH_RE.fullmatch(tx_hash) else None,
        wallet_address=normalized,
        address_short=_short_address(wallet_address),
        action_type="UNKNOWN",
        raw_payload_hash=_hash_payload(payload),
        source_url=source_url,
        confidence_score=0.75 if ok else 0.20,
        validation_status=ExplorerSourceStatus(status) if status in ExplorerSourceStatus.__members__ else ExplorerSourceStatus.EVENT_WITHOUT_ADDRESS,
        raw_payload=payload,
    )


def _to_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, sort_keys=True, default=str)


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_to_text(payload).encode("utf-8")).hexdigest()


def _short_address(value: str | None) -> str | None:
    if not value:
        return None
    if "..." in value:
        return value
    if len(value) >= 10:
        return f"{value[:6]}...{value[-4:]}"
    return value


def _to_optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _action_type(raw: dict[str, Any]) -> str | None:
    explicit = raw.get("action_type") or raw.get("type")
    if explicit:
        return str(explicit)
    action = raw.get("action")
    if isinstance(action, dict):
        return _to_optional_str(action.get("type"))
    if isinstance(action, list) and action:
        return str(action[0])
    return _to_optional_str(action)


def _first_order(action: Any) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None
    orders = action.get("orders")
    if isinstance(orders, list) and orders and isinstance(orders[0], dict):
        return orders[0]
    return None


def _coin_hint(raw: dict[str, Any]) -> str | None:
    explicit = raw.get("coin") or raw.get("asset")
    if explicit is not None:
        return str(explicit).upper()
    action = raw.get("action")
    order = _first_order(action)
    if order and order.get("a") is not None:
        # The Explorer stream exposes numeric asset ids. Keep this as a hint,
        # not a fake coin symbol; later modules can map ids via meta.
        return f"ASSET_{order.get('a')}"
    if isinstance(action, dict):
        cancels = action.get("cancels")
        if isinstance(cancels, list) and cancels and isinstance(cancels[0], dict):
            asset = cancels[0].get("asset")
            if asset is not None:
                return f"ASSET_{asset}"
    return None


def _side_hint(raw: dict[str, Any]) -> str | None:
    explicit = raw.get("side") or raw.get("direction")
    if explicit is not None:
        return str(explicit)
    order = _first_order(raw.get("action"))
    if order and order.get("b") is not None:
        return "buy" if bool(order.get("b")) else "sell"
    return None


def _size_hint(raw: dict[str, Any]) -> float | None:
    explicit = _to_float(raw.get("size") or raw.get("sz"))
    if explicit is not None:
        return explicit
    order = _first_order(raw.get("action"))
    return _to_float(order.get("s")) if order else None


def _price_hint(raw: dict[str, Any]) -> float | None:
    explicit = _to_float(raw.get("price") or raw.get("px"))
    if explicit is not None:
        return explicit
    order = _first_order(raw.get("action"))
    return _to_float(order.get("p")) if order else None
