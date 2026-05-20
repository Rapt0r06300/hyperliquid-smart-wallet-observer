from __future__ import annotations


def data_fresh(signal_age_ms: int, max_signal_age_ms: int) -> bool:
    return signal_age_ms <= max_signal_age_ms
