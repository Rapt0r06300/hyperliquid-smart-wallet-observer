from __future__ import annotations

import hashlib
import json
from typing import Any


class EventDedupe:
    def __init__(self, max_keys: int = 10_000) -> None:
        self.max_keys = max_keys
        self._seen: list[str] = []
        self._set: set[str] = set()

    def is_duplicate(self, key: str) -> bool:
        if key in self._set:
            return True
        self._seen.append(key)
        self._set.add(key)
        if len(self._seen) > self.max_keys:
            old = self._seen.pop(0)
            self._set.discard(old)
        return False

    def seen(self, key: str) -> bool:
        return self.is_duplicate(key)

    def accept_hyperliquid_message(self, message: dict[str, Any]) -> bool:
        """Return True when a WS message contains at least one unseen item.

        Hyperliquid subscription acknowledgements can include snapshot payloads
        tagged with ``isSnapshot: true``. We dedupe at item level so a snapshot
        arriving after already-processed updates cannot create duplicate fills
        or duplicate state events, while a mixed snapshot with new items is
        still accepted.
        """

        keys = hyperliquid_message_keys(message)
        if not keys:
            fallback = _stable_hash(message)
            return not self.is_duplicate(f"raw:{fallback}")
        accepted = False
        for key in keys:
            if not self.is_duplicate(key):
                accepted = True
        return accepted


def hyperliquid_message_keys(message: dict[str, Any]) -> list[str]:
    channel = str(message.get("channel") or message.get("type") or "unknown")
    data = message.get("data")
    if isinstance(data, list):
        return [_item_key(channel, item, message) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("fills") if isinstance(data.get("fills"), list) else None
        if items is not None:
            return [_item_key(channel, item, data) for item in items if isinstance(item, dict)]
        return [_item_key(channel, data, message)]
    return []


def _item_key(channel: str, item: dict[str, Any], parent: dict[str, Any]) -> str:
    user = str(item.get("user") or parent.get("user") or "").lower()
    coin = str(item.get("coin") or parent.get("coin") or "").upper()
    stable_identity = (
        item.get("hash")
        or item.get("tid")
        or item.get("oid")
        or item.get("cloid")
        or item.get("time")
        or item.get("timestamp")
        or _stable_hash(item)
    )
    return f"{channel}:{user}:{coin}:{stable_identity}"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
