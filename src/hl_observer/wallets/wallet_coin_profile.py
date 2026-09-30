from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from hl_observer.utils.time import now_ms


class WalletCoinProfile(BaseModel):
    wallet_address: str
    coin: str
    window: str = "latest"
    computed_at_ms: int
    fills_count: int = 0
    deltas_count: int = 0
    estimated_pnl_usdc: float | None = None
    estimated_roi_pct: float | None = None
    estimated_volume_usdc: float = 0.0
    win_rate: float | None = None
    profit_factor: float | None = None
    max_drawdown_pct: float | None = None
    last_activity_ms: int | None = None
    copyability_score: float = 0.0
    liquidity_score: float = 0.0
    toxicity_score: float = 0.0
    final_coin_score: float = 0.0
    confidence_score: float = 0.0
    status: str = "INCOMPLETE"


def build_wallet_coin_profiles(
    wallet_address: str,
    fills: list[dict[str, Any]],
    *,
    deltas_by_coin: dict[str, int] | None = None,
    liquidity_by_coin: dict[str, float] | None = None,
    min_fills_for_score: int = 3,
) -> list[WalletCoinProfile]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        coin = str(fill.get("coin") or fill.get("coinName") or "UNKNOWN").upper()
        grouped[coin].append(fill)
    profiles: list[WalletCoinProfile] = []
    for coin, coin_fills in grouped.items():
        profiles.append(
            build_wallet_coin_profile(
                wallet_address,
                coin,
                coin_fills,
                deltas_count=(deltas_by_coin or {}).get(coin, 0),
                liquidity_score=(liquidity_by_coin or {}).get(coin, 0.0),
                min_fills_for_score=min_fills_for_score,
            )
        )
    return profiles


def build_wallet_coin_profile(
    wallet_address: str,
    coin: str,
    fills: list[dict[str, Any]],
    *,
    deltas_count: int = 0,
    liquidity_score: float = 0.0,
    min_fills_for_score: int = 3,
) -> WalletCoinProfile:
    total_volume = 0.0
    pnl_values: list[float] = []
    last_activity_ms: int | None = None
    for fill in fills:
        price = _safe_float(fill.get("px") or fill.get("price")) or 0.0
        size = _safe_float(fill.get("sz") or fill.get("size")) or 0.0
        total_volume += abs(price * size)
        pnl = _safe_float(fill.get("closedPnl") or fill.get("closed_pnl"))
        if pnl is not None:
            pnl_values.append(pnl)
        ts = _safe_int(fill.get("time") or fill.get("timestamp"))
        if ts is not None:
            last_activity_ms = max(last_activity_ms or ts, ts)
    estimated_pnl = sum(pnl_values) if pnl_values else None
    estimated_roi = estimated_pnl / total_volume * 100 if estimated_pnl is not None and total_volume > 0 else None
    wins = sum(1 for pnl in pnl_values if pnl > 0)
    losses = sum(1 for pnl in pnl_values if pnl < 0)
    win_rate = wins / len(pnl_values) if pnl_values else None
    gross_profit = sum(pnl for pnl in pnl_values if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnl_values if pnl < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    copyability = min(100.0, (len(fills) / max(1, min_fills_for_score)) * 35.0 + liquidity_score * 0.65)
    confidence = min(1.0, len(fills) / max(1, min_fills_for_score))
    status = "SCORABLE" if len(fills) >= min_fills_for_score else "INCOMPLETE"
    return WalletCoinProfile(
        wallet_address=wallet_address,
        coin=coin.upper(),
        computed_at_ms=now_ms(),
        fills_count=len(fills),
        deltas_count=deltas_count,
        estimated_pnl_usdc=estimated_pnl,
        estimated_roi_pct=estimated_roi,
        estimated_volume_usdc=total_volume,
        win_rate=win_rate,
        profit_factor=profit_factor,
        last_activity_ms=last_activity_ms,
        copyability_score=copyability,
        liquidity_score=liquidity_score,
        toxicity_score=0.0,
        final_coin_score=0.0,
        confidence_score=confidence,
        status=status,
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

