from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.models import Signal


def has_sufficient_signal_data(signal: Signal, *, min_confidence: float = 0.5) -> bool:
    return signal.confidence >= min_confidence
