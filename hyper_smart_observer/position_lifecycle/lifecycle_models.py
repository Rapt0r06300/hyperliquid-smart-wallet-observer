from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from hyper_smart_observer.hyperliquid_client.models import PositionActionType


@dataclass(frozen=True)
class PositionAction:
    wallet_address: str
    coin: str
    action_type: PositionActionType
    timestamp: datetime
    size: float | None = None
    price: float | None = None
    closed_pnl: float | None = None
    fee: float | None = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    action_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class PositionLifecycle:
    wallet_address: str
    coin: str
    actions: list[PositionAction]
    confidence: float
    status: str
    warnings: list[str] = field(default_factory=list)
