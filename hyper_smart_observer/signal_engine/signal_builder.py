from __future__ import annotations

from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
from uuid import uuid4

from hyper_smart_observer.hyperliquid_client.models import Signal, SignalState


def build_observed_signal(wallet_address: str, coin: str, side: str, reason: str) -> Signal:
    return Signal(
        signal_id=str(uuid4()),
        wallet_address=wallet_address.lower(),
        coin=coin.upper(),
        side=side,
        confidence=0.0,
        created_at=datetime.now(UTC),
        state=SignalState.OBSERVED,
        reason=reason,
    )
