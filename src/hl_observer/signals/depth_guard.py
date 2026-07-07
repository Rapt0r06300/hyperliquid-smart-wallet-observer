"""V13 #155 — Depth Guard (Harrier): validate REAL orderbook liquidity BEFORE each entry."""

from __future__ import annotations

from hl_observer.paper_trading.exec_model import DepthExecutionResult, simulate_depth_execution


def depth_guard(*, bid_depth_usd: float, ask_depth_usd: float, side: str,
                needed_usd: float, min_depth_usd: float = 200.0,
                max_consume_fraction: float = 0.25) -> tuple[bool, str | None]:
    """Block an entry if the side we must hit is too thin to absorb our size cleanly."""
    s = str(side or "").upper()
    book_usd = float(ask_depth_usd if s in {"LONG", "BUY"} else bid_depth_usd)
    if book_usd < float(min_depth_usd):
        return False, "DEPTH_TOO_LOW"
    if float(needed_usd) > book_usd * float(max_consume_fraction):
        return False, "SIZE_EXCEEDS_DEPTH"      # our order would eat too much of the book
    return True, None


def depth_fill_guard(
    *,
    side: str,
    needed_usd: float,
    mid_price: float,
    asks: tuple[tuple[float, float], ...] = (),
    bids: tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.85,
    max_slippage_bps: float = 20.0,
) -> tuple[bool, str | None, DepthExecutionResult]:
    """Block paper entries whose explicit book levels cannot fill cleanly."""

    result = simulate_depth_execution(
        side=side,
        notional_usdc=needed_usd,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        min_fill_ratio=min_fill_ratio,
    )
    if result.missed:
        return False, result.reason, result
    if result.partial:
        return False, "PARTIAL_FILL_BELOW_FULL_COPY_STANDARD", result
    if result.slippage_bps > float(max_slippage_bps):
        return False, "DEPTH_SLIPPAGE_TOO_HIGH", result
    return True, None, result


__all__ = ["depth_fill_guard", "depth_guard"]
