from __future__ import annotations


def trailing_stop_price(side: str, best_price: float, trailing_bps: float) -> float:
    if side.lower() == "long":
        return best_price * (1 - trailing_bps / 10000.0)
    return best_price * (1 + trailing_bps / 10000.0)
