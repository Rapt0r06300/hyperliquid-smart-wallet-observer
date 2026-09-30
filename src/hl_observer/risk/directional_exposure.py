"""Fail-closed directional and concentration exposure guard."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

NET_EXPOSURE_PCT_ENV = "HYPERSMART_MAX_NET_DIRECTIONAL_PCT"
COIN_CONCENTRATION_PCT_ENV = "HYPERSMART_MAX_COIN_NOTIONAL_PCT"
DEFAULT_NET_EXPOSURE_PCT = 100.0
DEFAULT_COIN_CONCENTRATION_PCT = 60.0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _env_pct(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        value = default
    else:
        value = _f(raw, float("nan"))
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"invalid exposure limit: {name}")
    return value


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    gross_usdt: float
    net_usdt: float
    long_usdt: float
    short_usdt: float
    by_coin: dict[str, float]

    @property
    def net_bias(self) -> str:
        if abs(self.net_usdt) < 1e-9:
            return "NEUTRAL"
        return "LONG" if self.net_usdt > 0 else "SHORT"


def snapshot_exposure(positions: Mapping[Any, Any] | Iterable[Any]) -> ExposureSnapshot:
    rows = positions.values() if isinstance(positions, Mapping) else positions
    gross = net = longs = shorts = 0.0
    by_coin: dict[str, float] = {}
    for position in rows:
        if isinstance(position, Mapping):
            get = position.get
        else:
            get = lambda key: getattr(position, key, None)
        raw_size = get("size")
        if raw_size is None:
            raw_size = get("quantity")
        size = abs(_f(raw_size))
        raw_price = get("avg_price")
        if raw_price is None:
            raw_price = get("average_entry_price")
        if raw_price is None:
            raw_price = get("entry_price")
        price = _f(raw_price)
        if size <= 0.0 or price <= 0.0:
            continue
        notional = size * price
        side = str(get("direction") or get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            side = str(get("position_side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            continue
        sign = 1.0 if side == "LONG" else -1.0
        gross += notional
        net += sign * notional
        if sign > 0.0:
            longs += notional
        else:
            shorts += notional
        coin = str(get("coin") or "?").upper()
        by_coin[coin] = by_coin.get(coin, 0.0) + notional
    return ExposureSnapshot(round(gross, 8), round(net, 8), round(longs, 8), round(shorts, 8), by_coin)


def directional_refusal(
    positions: Mapping[Any, Any] | Iterable[Any],
    *,
    coin: str,
    side: str,
    new_notional_usdt: float,
    equity_usdt: float,
    max_net_pct: float | None = None,
    max_coin_pct: float | None = None,
) -> str:
    try:
        equity = float(equity_usdt)
        notional = float(new_notional_usdt)
    except (TypeError, ValueError, OverflowError):
        return "INVALID_EXPOSURE_INPUT"
    if not math.isfinite(equity) or not math.isfinite(notional) or equity <= 0.0 or notional <= 0.0:
        return "INVALID_EXPOSURE_INPUT"
    side_up = str(side or "").upper()
    if side_up not in {"LONG", "SHORT"}:
        return "INVALID_EXPOSURE_SIDE"
    net_limit = max_net_pct if max_net_pct is not None else DEFAULT_NET_EXPOSURE_PCT
    coin_limit = max_coin_pct if max_coin_pct is not None else DEFAULT_COIN_CONCENTRATION_PCT
    try:
        net_cap = equity * _env_pct(NET_EXPOSURE_PCT_ENV, net_limit) / 100.0
        coin_cap = equity * _env_pct(COIN_CONCENTRATION_PCT_ENV, coin_limit) / 100.0
    except (TypeError, ValueError, OverflowError):
        return "INVALID_EXPOSURE_LIMIT"
    snap = snapshot_exposure(positions)
    sign = 1.0 if side_up == "LONG" else -1.0
    net_after = snap.net_usdt + sign * notional
    if abs(net_after) > net_cap and abs(net_after) >= abs(snap.net_usdt):
        return "NET_DIRECTIONAL_EXPOSURE_TOO_HIGH"
    coin_after = snap.by_coin.get(str(coin or "?").upper(), 0.0) + notional
    if coin_after > coin_cap:
        return "COIN_CONCENTRATION_TOO_HIGH"
    return ""


__all__ = [
    "COIN_CONCENTRATION_PCT_ENV",
    "DEFAULT_COIN_CONCENTRATION_PCT",
    "DEFAULT_NET_EXPOSURE_PCT",
    "ExposureSnapshot",
    "NET_EXPOSURE_PCT_ENV",
    "directional_refusal",
    "snapshot_exposure",
]
