"""
Flux de marché (v4_trades) → signaux momentum — READ-ONLY / PAPER.

Le canal public `v4_trades` diffuse TOUS les trades d'un marché en temps réel
(sans adresse — anonyme). Fiable et massif, sans abonnement par wallet, sans node.

Stratégie: on agrège l'achat/vente AGRESSIF (taker side) sur une fenêtre glissante.
Quand un côté domine fortement (déséquilibre) sur un marché liquide → signal
directionnel (LONG si l'achat domine, SHORT sinon). Ce n'est PAS de la copie de
wallet : c'est du momentum d'order-flow. Les exits ATR + le coupe-circuit bornent
le risque. Honnête: le momentum peut se retourner — c'est filtré par le volume,
le déséquilibre, la liquidité et l'edge, puis validé par le sweep.

Logique pure testable. Aucune méthode d'ordre/signature.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FlowSignal:
    market: str
    direction: str            # "LONG" | "SHORT"
    buy_usdc: float
    sell_usdc: float
    trades: int
    large_trade_usdc: float = 0.0

    @property
    def total_usdc(self) -> float:
        return self.buy_usdc + self.sell_usdc

    @property
    def imbalance(self) -> float:
        t = self.total_usdc
        return abs(self.buy_usdc - self.sell_usdc) / t if t > 0 else 0.0


def parse_trades(contents: dict) -> list[tuple[str, float, float]]:
    """Extraire (side, size, price) d'un message v4_trades (défensif)."""
    if not isinstance(contents, dict):
        return []
    raw = contents.get("trades") or contents.get("items") or []
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, float, float]] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        side = str(t.get("side", "")).upper()
        if side not in ("BUY", "SELL"):
            continue
        try:
            size = float(t.get("size", 0) or 0)
            price = float(t.get("price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if size > 0 and price > 0:
            out.append((side, size, price))
    return out


class MarketFlowWindow:
    """Fenêtre glissante des trades (ts, market, side, usdc)."""

    def __init__(self, window_ms: int = 12000, maxlen: int = 500_000) -> None:
        self.window_ms = window_ms
        self.maxlen = maxlen
        self._items: deque = deque()

    def add(self, ts_ms: int, market: str, side: str, usdc: float) -> None:
        if not market or usdc <= 0:
            return
        self._items.append((ts_ms, market, side, usdc))
        while len(self._items) > self.maxlen:
            self._items.popleft()

    def prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.window_ms
        while self._items and self._items[0][0] < cutoff:
            self._items.popleft()

    def items(self) -> list:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


def detect_flow_signals(
    items: list,
    min_volume_usdc: float,
    min_imbalance: float,
    min_trades: int = 3,
) -> list[FlowSignal]:
    """
    Détecter les déséquilibres d'order-flow. `items` = [(ts, market, side, usdc)].
    Garde les marchés avec:
    - volume ≥ min_volume_usdc
    - déséquilibre ≥ min_imbalance
    - nombre de trades ≥ min_trades
    """
    agg: dict[str, list] = {}
    for _ts, market, side, usdc in items:
        a = agg.setdefault(market, [0.0, 0.0, 0, 0.0, 0.0])
        if side == "BUY":
            a[0] += usdc
            a[3] = max(a[3], float(usdc or 0.0))
        else:
            a[1] += usdc
            a[4] = max(a[4], float(usdc or 0.0))
        a[2] += 1
    out: list[FlowSignal] = []
    for market, (buy, sell, cnt, max_buy, max_sell) in agg.items():
        total = buy + sell
        if total < min_volume_usdc:
            continue
        if cnt < min_trades:
            continue
        imb = abs(buy - sell) / total if total > 0 else 0.0
        if imb < min_imbalance:
            continue
        is_long = buy >= sell
        out.append(FlowSignal(
            market=market, direction="LONG" if is_long else "SHORT",
            buy_usdc=buy, sell_usdc=sell, trades=cnt,
            large_trade_usdc=max_buy if is_long else max_sell,
        ))
    out.sort(key=lambda s: s.total_usdc, reverse=True)
    return out


def build_cluster_from_flow(signal: FlowSignal, mark_price: float, now_ms: int):
    """FlowSignal → ClusterSignal (origin='stream') pour le moteur de décision."""
    from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
    return ClusterSignal(
        market_id=signal.market,
        side=signal.direction,
        wallet_count=1,
        participating_wallets=[],
        total_notional_usdc=signal.total_usdc,
        first_wallet_opened_ms=now_ms,
        last_wallet_opened_ms=now_ms,
        signal_age_ms=0,
        avg_entry_price=float(mark_price or 0.0),
        signal_strength=min(1.0, signal.imbalance),
        market_priority=0.5,
        is_fresh=True,
        cluster_id=f"flow:{signal.market}:{signal.direction}:{now_ms}",
        origin="stream",
        flow_trade_count=signal.trades,
        flow_large_trade_usdc=signal.large_trade_usdc,
    )


class MarketFlowMonitor:
    """
    Abonne le WS public `v4_trades` sur une liste de marchés liquides, agrège le
    flux, et expose `drain_and_detect()`. READ-ONLY. Aucune adresse, aucun ordre.
    """

    def __init__(
        self,
        ws_url: str,
        markets: list[str],
        window_ms: int = 8000,
        large_trade_threshold_usdc: float = 50_000.0,
    ) -> None:
        self.ws_url = ws_url
        self.markets = list(markets)
        self.window = MarketFlowWindow(window_ms=window_ms)
        self.large_trade_threshold_usdc = float(large_trade_threshold_usdc or 50_000.0)
        self._lock = threading.Lock()
        self._pending: list = []
        self._latest_prices: dict[str, tuple[float, int]] = {}
        self._ws = None
        self.stats = {
            "trades_seen": 0,
            "signals": 0,
            "ws_status": "DISCONNECTED",
            "ws_healthy": False,
            "subscriptions_requested": 0,
            "latest_price_markets": 0,
        }

    def _on_message(self, msg) -> None:
        if getattr(msg, "channel", "") != "v4_trades":
            return
        market = getattr(msg, "id", "") or ""
        data = getattr(msg, "data", {}) or {}
        now = int(time.time() * 1000)
        with self._lock:
            for side, size, price in parse_trades(data):
                usdc = size * price
                self._pending.append((now, market, side, usdc))
                self._latest_prices[market] = (price, now)
                self.stats["trades_seen"] += 1
                if usdc >= self.large_trade_threshold_usdc:
                    self.stats["large_trades_seen"] = int(self.stats.get("large_trades_seen", 0) or 0) + 1
                    self.stats["last_large_trade_market"] = market
                    self.stats["last_large_trade_side"] = side
                    self.stats["last_large_trade_usdc"] = round(usdc, 2)
                    self.stats["last_large_trade_at_ms"] = now
                self.stats["last_trade_market"] = market
                self.stats["last_trade_price"] = price
                self.stats["last_trade_at_ms"] = now
            if len(self._pending) > 200_000:
                self._pending = self._pending[-100_000:]
            self.stats["latest_price_markets"] = len(self._latest_prices)

    def start(self) -> None:  # pragma: no cover - réseau
        try:
            from hyper_smart_observer.dydx_v4.ws_client import DydxIndexerWsClient
            self._ws = DydxIndexerWsClient(self.ws_url, on_message=self._on_message)
            self._ws.start()
            self.stats["subscriptions_requested"] = len(self.markets)
            self._refresh_ws_stats()
            for m in self.markets:
                try:
                    self._ws.subscribe_trades(m)
                except Exception:
                    pass
            logger.info("MarketFlowMonitor démarré: %d marchés (v4_trades)", len(self.markets))
        except Exception as e:
            logger.warning("MarketFlowMonitor indisponible: %s", e)

    def stop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                pass
        self._refresh_ws_stats()

    def _refresh_ws_stats(self) -> None:
        if self._ws is None:
            self.stats["ws_status"] = "DISCONNECTED"
            self.stats["ws_healthy"] = False
            return
        try:
            status = getattr(self._ws, "status", "UNKNOWN")
            self.stats["ws_status"] = getattr(status, "value", str(status))
            self.stats["ws_healthy"] = bool(getattr(self._ws, "is_healthy", False))
            self.stats["seconds_since_last_message"] = round(
                float(getattr(self._ws, "seconds_since_last_message", float("inf"))), 3
            )
            last_trade_at = int(self.stats.get("last_trade_at_ms") or 0)
            if last_trade_at:
                self.stats["seconds_since_last_trade"] = round(
                    max(0.0, (time.time() * 1000 - last_trade_at) / 1000.0), 3
                )
        except Exception:
            self.stats["ws_status"] = "UNKNOWN"
            self.stats["ws_healthy"] = False

    def latest_prices(self, max_age_ms: int = 5_000) -> dict[str, float]:
        """
        Derniers prix réellement vus sur le flux public `v4_trades`.

        Ces marks sont destinés au mark-to-market de la simulation: ils ne
        déclenchent aucun ordre et ne remplacent pas un vrai signal de wallet.
        """
        now = int(time.time() * 1000)
        cutoff = now - max(0, int(max_age_ms))
        with self._lock:
            out = {
                market: price
                for market, (price, ts_ms) in self._latest_prices.items()
                if ts_ms >= cutoff and price > 0
            }
            self.stats["latest_price_markets"] = len(out)
            last_trade_at = int(self.stats.get("last_trade_at_ms") or 0)
            if last_trade_at:
                self.stats["seconds_since_last_trade"] = round(
                    max(0.0, (now - last_trade_at) / 1000.0), 3
                )
            return out

    def drain_and_detect(
        self,
        min_volume_usdc: float,
        min_imbalance: float,
        min_trades: int = 3,
    ) -> list[FlowSignal]:
        self._refresh_ws_stats()
        now = int(time.time() * 1000)
        with self._lock:
            pending = self._pending
            self._pending = []
        for (ts, market, side, usdc) in pending:
            self.window.add(ts, market, side, usdc)
        self.window.prune(now)
        signals = detect_flow_signals(
            self.window.items(), min_volume_usdc, min_imbalance, min_trades
        )
        self.stats["signals"] = len(signals)
        return signals


__all__ = [
    "FlowSignal",
    "parse_trades",
    "MarketFlowWindow",
    "detect_flow_signals",
    "build_cluster_from_flow",
    "MarketFlowMonitor",
]
