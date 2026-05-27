from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.utils.time import now_ms


def build_signal_candidate(
    *,
    signal_id: str,
    source_wallet: str,
    coin: str,
    side: str,
    signal_type: str,
    observed_price: float,
    timestamp_ms: int,
    **kwargs,
) -> SignalCandidate:
    # Ensure signal_age_ms is not duplicated if passed in kwargs
    if "signal_age_ms" not in kwargs:
        kwargs["signal_age_ms"] = max(0, now_ms() - timestamp_ms)

    return SignalCandidate(
        id=signal_id,
        source_wallet=source_wallet,
        coin=coin,
        side=side,  # type: ignore[arg-type]
        signal_type=signal_type,  # type: ignore[arg-type]
        observed_price=observed_price,
        timestamp_ms=timestamp_ms,
        **kwargs,
    )
