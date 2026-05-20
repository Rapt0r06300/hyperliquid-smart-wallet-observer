from __future__ import annotations


def no_trade_precision(avoided_losses: int, rejected_count: int) -> float:
    if rejected_count <= 0:
        return 0.0
    return avoided_losses / rejected_count
