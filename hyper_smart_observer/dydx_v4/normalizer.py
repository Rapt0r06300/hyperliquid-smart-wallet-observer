"""
Normalisation des données brutes dYdX v4 vers les modèles internes.

Jamais de données inventées. Si un champ est manquant, lever une exception
ou retourner None explicitement.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NormalizedFill,
    NormalizedMarket,
    NormalizedOrder,
    NormalizedPosition,
    NormalizedSubaccount,
    NormalizedTrade,
    OrderSide,
    OrderStatus,
    PositionSide,
)

logger = logging.getLogger(__name__)


def _parse_iso_ms(iso_str: Optional[str]) -> int:
    """Convertir une chaîne ISO 8601 en millisecondes epoch."""
    if not iso_str:
        return int(time.time() * 1000)
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def _safe_float(val: Optional[str | float | int], default: float = 0.0) -> float:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def normalize_market(raw: dict) -> Optional[NormalizedMarket]:
    """Normaliser un marché dYdX v4 brut."""
    try:
        ticker = raw.get("ticker", "")
        if not ticker:
            return None

        best_bid = _safe_float(raw.get("bestBid"))
        best_ask = _safe_float(raw.get("bestAsk"))
        spread_bps = 0.0
        mid = _safe_float(raw.get("midPrice"))
        if mid > 0 and best_bid > 0 and best_ask > 0:
            spread_bps = ((best_ask - best_bid) / mid) * 10_000

        parts = ticker.split("-")
        base = parts[0] if len(parts) >= 1 else ticker
        quote = parts[1] if len(parts) >= 2 else "USD"

        return NormalizedMarket(
            market_id=ticker,
            base_asset=base,
            quote_asset=quote,
            tick_size=_safe_float(raw.get("tickSize")),
            step_size=_safe_float(raw.get("stepSize")),
            min_order_size=_safe_float(raw.get("minOrderSize")),
            oracle_price=_safe_float(raw.get("oraclePrice")),
            index_price=_safe_float(raw.get("indexPrice")),
            mid_price=mid if mid > 0 else (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0,
            best_bid=best_bid,
            best_ask=best_ask,
            spread_bps=round(spread_bps, 2),
            volume_24h=_safe_float(raw.get("volume24H")),
            open_interest=_safe_float(raw.get("openInterest")),
            is_active=raw.get("status", "") in ("ACTIVE", "active"),
            updated_at_ms=_parse_iso_ms(raw.get("updatedAt")),
            raw=raw,
        )
    except Exception as e:
        logger.error("normalize_market error: %s | raw=%s", e, str(raw)[:200])
        return None


def normalize_subaccount(raw: dict) -> Optional[NormalizedSubaccount]:
    """Normaliser un subaccount dYdX v4 brut."""
    try:
        address = raw.get("address", "")
        subnum = int(raw.get("subaccountNumber", 0))
        equity = _safe_float(raw.get("equity"))
        free_col = _safe_float(raw.get("freeCollateral"))
        margin_usage = 1.0 - (free_col / equity) if equity > 0 else 0.0
        leverage = _safe_float(raw.get("leverage"))

        return NormalizedSubaccount(
            account_address=address,
            subaccount_number=subnum,
            equity=equity,
            free_collateral=free_col,
            margin_usage=min(1.0, max(0.0, margin_usage)),
            leverage=leverage,
            updated_at_ms=_parse_iso_ms(raw.get("updatedAt")),
            raw=raw,
        )
    except Exception as e:
        logger.error("normalize_subaccount error: %s", e)
        return None


def normalize_position(raw: dict) -> Optional[NormalizedPosition]:
    """Normaliser une position dYdX v4 brute."""
    try:
        status_raw = raw.get("status", "")
        side_raw = raw.get("side", "").upper()
        side = PositionSide.LONG if side_raw == "LONG" else (
            PositionSide.SHORT if side_raw == "SHORT" else PositionSide.UNKNOWN
        )
        if side == PositionSide.UNKNOWN:
            logger.warning("normalize_position: UNKNOWN side — skipping")
            return None

        address = raw.get("address", "")
        subnum = int(raw.get("subaccountNumber", 0))
        market_id = raw.get("market", "")

        return NormalizedPosition(
            account_address=address,
            subaccount_number=subnum,
            market_id=market_id,
            side=side,
            size=abs(_safe_float(raw.get("size"))),
            entry_price=_safe_float(raw.get("entryPrice")),
            mark_price=_safe_float(raw.get("exitPrice") or raw.get("entryPrice")),
            unrealized_pnl=_safe_float(raw.get("unrealizedPnl")),
            realized_pnl=_safe_float(raw.get("realizedPnl")),
            net_funding=_safe_float(raw.get("netFunding")),
            margin=_safe_float(raw.get("initialMargin")),
            leverage=_safe_float(raw.get("leverage")),
            liquidation_price=_safe_float(raw.get("liquidationPrice")) or None,
            opened_at_ms=_parse_iso_ms(raw.get("createdAt")),
            updated_at_ms=_parse_iso_ms(raw.get("updatedAt") or raw.get("createdAt")),
            raw=raw,
        )
    except Exception as e:
        logger.error("normalize_position error: %s | raw=%s", e, str(raw)[:200])
        return None


def normalize_fill(raw: dict) -> Optional[NormalizedFill]:
    """Normaliser un fill dYdX v4 brut."""
    try:
        side_raw = raw.get("side", "").upper()
        side = OrderSide.BUY if side_raw == "BUY" else (
            OrderSide.SELL if side_raw == "SELL" else None
        )
        if side is None:
            logger.warning("normalize_fill: unknown side '%s'", side_raw)
            return None

        address = raw.get("address", "")
        subnum = int(raw.get("subaccountNumber", 0))

        return NormalizedFill(
            fill_id=raw.get("id", ""),
            account_address=address,
            subaccount_number=subnum,
            market_id=raw.get("market", ""),
            side=side,
            size=_safe_float(raw.get("size")),
            price=_safe_float(raw.get("price")),
            fee=_safe_float(raw.get("fee")),
            liquidity=raw.get("liquidity", "TAKER").upper(),
            created_at_ms=_parse_iso_ms(raw.get("createdAt")),
            order_id=raw.get("orderId"),
            raw=raw,
        )
    except Exception as e:
        logger.error("normalize_fill error: %s | raw=%s", e, str(raw)[:200])
        return None


def normalize_trade(raw: dict) -> Optional[NormalizedTrade]:
    """Normaliser un trade public dYdX v4."""
    try:
        side_raw = raw.get("side", "").upper()
        side = OrderSide.BUY if side_raw == "BUY" else (
            OrderSide.SELL if side_raw == "SELL" else OrderSide.BUY
        )
        return NormalizedTrade(
            trade_id=raw.get("id", ""),
            market_id=raw.get("market", ""),
            side=side,
            size=_safe_float(raw.get("size")),
            price=_safe_float(raw.get("price")),
            created_at_ms=_parse_iso_ms(raw.get("createdAt")),
            type=raw.get("type", "LIMIT"),
            raw=raw,
        )
    except Exception as e:
        logger.error("normalize_trade error: %s", e)
        return None


def infer_lifecycle(
    prev_size: float,
    new_size: float,
    side: PositionSide,
    fill_side: Optional[OrderSide] = None,
) -> LifecycleEvent:
    """
    Inférer le lifecycle depuis la variation de taille.

    OPEN: prev=0, new>0
    ADD: prev>0, new>prev (même sens)
    REDUCE: prev>0, new<prev, new>0
    CLOSE: prev>0, new=0
    FLIP: prev>0, new>0 mais sens inverse → CLOSE + OPEN séparés
    UNKNOWN: cas impossible ou données manquantes
    """
    if prev_size < 0 or new_size < 0:
        return LifecycleEvent.UNKNOWN

    if prev_size == 0 and new_size > 0:
        return LifecycleEvent.OPEN

    if prev_size > 0:
        if new_size == 0:
            return LifecycleEvent.CLOSE
        if new_size > prev_size:
            return LifecycleEvent.ADD
        if 0 < new_size < prev_size:
            return LifecycleEvent.REDUCE

    return LifecycleEvent.UNKNOWN
