"""Microstructure features from real Hyperliquid trades (S4 — V9 fusion).

Pure, deterministic helpers over real trade/print data:
CVD (cumulative volume delta), RVOL (relative volume), anchored-VWAP,
impulse, basis (perp vs index) and liquidation pressure.

SAFETY: read-only derivation. Data absent or unparsable -> ``None`` /
``data_quality`` low. Nothing is fabricated; a signal is never an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hl_observer.features.market import safe_float


@dataclass(frozen=True, slots=True)
class MicrostructureFeatures:
    cvd: float | None
    buy_volume: float
    sell_volume: float
    rvol: float | None
    anchored_vwap: float | None
    impulse_bps: float | None
    basis_bps: float | None
    liquidation_notional: float
    trade_count: int
    data_quality: str


def _trade_side_sign(raw: Any) -> float | None:
    """Map a Hyperliquid trade side to an aggressor sign (+1 buy / -1 sell)."""
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if token in {"b", "buy", "bid", "long", "+1", "1"}:
        return 1.0
    if token in {"a", "s", "sell", "ask", "short", "-1"}:
        return -1.0
    return None


def _trade_px_sz_side(trade: Any) -> tuple[float | None, float | None, float | None]:
    if isinstance(trade, dict):
        px = safe_float(trade.get("px") or trade.get("price"))
        sz = safe_float(trade.get("sz") or trade.get("size") or trade.get("qty"))
        side = _trade_side_sign(trade.get("side") or trade.get("dir") or trade.get("aggressor"))
        return px, sz, side
    if isinstance(trade, (list, tuple)) and len(trade) >= 2:
        return safe_float(trade[0]), safe_float(trade[1]), None
    return None, None, None


def compute_cvd(trades: list[Any] | None) -> tuple[float | None, float, float]:
    """Cumulative volume delta plus split buy/sell notional.

    Returns ``(cvd, buy_volume, sell_volume)``. ``cvd`` is ``None`` when no
    trade carries a usable aggressor side (we never guess a side).
    """
    if not trades:
        return None, 0.0, 0.0
    buy = 0.0
    sell = 0.0
    has_side = False
    for trade in trades:
        px, sz, side = _trade_px_sz_side(trade)
        if px is None or sz is None or sz <= 0 or side is None:
            continue
        has_side = True
        notional = px * sz
        if side > 0:
            buy += notional
        else:
            sell += notional
    if not has_side:
        return None, buy, sell
    return buy - sell, buy, sell


def compute_rvol(current_volume: float | None, historical_volumes: list[Any] | None) -> float | None:
    """Relative volume = current window volume / mean of historical windows."""
    current = safe_float(current_volume)
    if current is None or not historical_volumes:
        return None
    values = [v for v in (safe_float(x) for x in historical_volumes) if v is not None and v >= 0]
    if not values:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    return current / mean


def compute_anchored_vwap(trades: list[Any] | None, *, anchor_index: int = 0) -> float | None:
    """Volume-weighted average price from ``anchor_index`` onward."""
    if not trades:
        return None
    anchor = max(0, anchor_index)
    pv = 0.0
    vol = 0.0
    for trade in trades[anchor:]:
        px, sz, _ = _trade_px_sz_side(trade)
        if px is None or sz is None or px <= 0 or sz <= 0:
            continue
        pv += px * sz
        vol += sz
    if vol <= 0:
        return None
    return pv / vol


def compute_impulse_bps(prices: list[Any] | None, *, window: int = 5) -> float | None:
    """Short-horizon price impulse in bps over the last ``window`` prints."""
    if not prices:
        return None
    clean = [p for p in (safe_float(x) for x in prices) if p is not None and p > 0]
    if len(clean) < 2:
        return None
    recent = clean[-(window + 1):] if window > 0 else clean
    start = recent[0]
    end = recent[-1]
    if start <= 0:
        return None
    return (end - start) / start * 10_000.0


def compute_basis_bps(perp_mark: float | None, index_price: float | None) -> float | None:
    """Perp-vs-index basis in bps (positive = perp rich)."""
    mark = safe_float(perp_mark)
    index = safe_float(index_price)
    if mark is None or index is None or index <= 0:
        return None
    return (mark - index) / index * 10_000.0


def compute_liquidation_notional(liquidations: list[Any] | None) -> float:
    if not liquidations:
        return 0.0
    total = 0.0
    for item in liquidations:
        if isinstance(item, dict):
            px = safe_float(item.get("px") or item.get("price"))
            sz = safe_float(item.get("sz") or item.get("size"))
            notional = safe_float(item.get("notional"))
            if notional is not None and notional >= 0:
                total += notional
            elif px is not None and sz is not None and px > 0 and sz > 0:
                total += px * sz
    return total


def compute_microstructure(
    *,
    trades: list[Any] | None = None,
    historical_volumes: list[Any] | None = None,
    perp_mark: float | None = None,
    index_price: float | None = None,
    liquidations: list[Any] | None = None,
    anchor_index: int = 0,
    impulse_window: int = 5,
) -> MicrostructureFeatures:
    cvd, buy, sell = compute_cvd(trades)
    current_volume = (buy + sell) if trades else None
    rvol = compute_rvol(current_volume, historical_volumes)
    vwap = compute_anchored_vwap(trades, anchor_index=anchor_index)
    prices = [safe_float(t.get("px")) if isinstance(t, dict) else None for t in (trades or [])]
    impulse = compute_impulse_bps([p for p in prices if p is not None], window=impulse_window)
    basis = compute_basis_bps(perp_mark, index_price)
    liq = compute_liquidation_notional(liquidations)
    count = len(trades or [])

    if not trades:
        quality = "MISSING"
    elif cvd is None or vwap is None:
        quality = "DEGRADED"
    else:
        quality = "OK"

    return MicrostructureFeatures(
        cvd=cvd,
        buy_volume=buy,
        sell_volume=sell,
        rvol=rvol,
        anchored_vwap=vwap,
        impulse_bps=impulse,
        basis_bps=basis,
        liquidation_notional=liq,
        trade_count=count,
        data_quality=quality,
    )
