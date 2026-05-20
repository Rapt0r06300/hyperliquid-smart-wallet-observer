from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.storage.models import RawEvent, RejectedSignal
from hl_observer.utils.time import now_ms


def stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class RawEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        wallet: str | None = None,
        coin: str | None = None,
        exchange_ts: int | None = None,
    ) -> RawEvent:
        event = RawEvent(
            source=source,
            event_type=event_type,
            wallet=wallet,
            coin=coin,
            exchange_ts=exchange_ts,
            local_received_ts=now_ms(),
            payload_json=payload,
            payload_hash=stable_payload_hash(payload),
        )
        self.session.add(event)
        return event


class RejectedSignalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, signal_id: str, decision: str, reason: str, raw: dict[str, Any]) -> RejectedSignal:
        rejected = RejectedSignal(
            signal_id=signal_id,
            decision=decision,
            reason=reason,
            raw_json=raw,
        )
        self.session.add(rejected)
        return rejected
