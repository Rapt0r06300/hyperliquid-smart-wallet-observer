"""
Client WebSocket Indexer dYdX v4 — READ-ONLY.

- Reconnect automatique
- Resubscribe après reconnexion
- Heartbeat/ping/pong
- Gap detection et recovery REST
- Diagnostics exploitables par dashboard/logs
- Mode DEGRADED si WS dégradé
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibilité Python 3.10."""
        def __str__(self) -> str:
            return self.value

from queue import Empty, Queue
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_TOP_TRADE_MARKETS = ["BTC-USD", "ETH-USD", "SOL-USD", "HYPE-USD", "XRP-USD"]

try:
    import websocket as _ws_lib
    _WEBSOCKET_AVAILABLE = True
except ImportError:
    _WEBSOCKET_AVAILABLE = False
    logger.warning("websocket-client non disponible — WS client désactivé")


class WsStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBED = "SUBSCRIBED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class WsMessage:
    """Message WebSocket reçu et normalisé."""
    channel: str
    type: str
    id: Optional[str]
    data: dict
    received_at_ms: int
    raw: str = ""


@dataclass(frozen=True)
class WsDiagnostics:
    """Snapshot de santé WS, sans secret et sans donnée privée."""
    status: str
    websocket_client_available: bool
    connected: bool
    healthy: bool
    degraded: bool
    subscriptions: int
    messages_received: int
    messages_dropped: int
    errors: int
    reconnect_count: int
    last_error: str
    seconds_since_last_message: float
    last_message_at_ms: int
    queue_size: int
    read_only: bool = True
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "websocket_client_available": self.websocket_client_available,
            "connected": self.connected,
            "healthy": self.healthy,
            "degraded": self.degraded,
            "subscriptions": self.subscriptions,
            "messages_received": self.messages_received,
            "messages_dropped": self.messages_dropped,
            "errors": self.errors,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "seconds_since_last_message": round(self.seconds_since_last_message, 3),
            "last_message_at_ms": self.last_message_at_ms,
            "queue_size": self.queue_size,
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


class DydxIndexerWsClient:
    """
    Client WebSocket Indexer dYdX v4.

    READ-ONLY: écoute uniquement, jamais d'envoi de transaction.
    Reconnect automatique, gap recovery via REST.
    """

    CHANNEL_MARKETS = "v4_markets"
    CHANNEL_TRADES = "v4_trades"
    CHANNEL_ORDERBOOK = "v4_orderbook"
    CHANNEL_SUBACCOUNTS = "v4_subaccounts"
    CHANNEL_BLOCK_HEIGHT = "v4_block_height"

    def __init__(
        self,
        ws_url: str,
        on_message: Optional[Callable[[WsMessage], None]] = None,
        on_gap_detected: Optional[Callable[[str, str], None]] = None,
        ping_interval_s: float = 30.0,
        reconnect_delay_s: float = 5.0,
        max_reconnect_attempts: int = 50,
        subscription_min_interval_s: float = 0.02,
    ) -> None:
        self.ws_url = ws_url
        self._on_message_cb = on_message
        self._on_gap_cb = on_gap_detected
        self.ping_interval_s = ping_interval_s
        self.reconnect_delay_s = reconnect_delay_s
        self.max_reconnect_attempts = max_reconnect_attempts
        self.subscription_min_interval_s = max(0.0, subscription_min_interval_s)

        self._ws: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._status = WsStatus.DISCONNECTED
        self._reconnect_count = 0
        self._last_message_at: float = 0.0
        self._last_message_at_ms: int = 0
        self._subscriptions: dict[str, dict] = {}
        self._message_queue: Queue[WsMessage] = Queue(maxsize=10_000)
        self._stop_event = threading.Event()
        self._send_lock = threading.Lock()
        self._last_subscription_send = 0.0

        self._last_sequence: dict[str, int] = {}
        self._messages_received = 0
        self._messages_dropped = 0
        self._errors = 0
        self._last_error = ""
        self._subscriptions_sent = 0

    @property
    def status(self) -> WsStatus:
        return self._status

    @property
    def is_healthy(self) -> bool:
        return self._status in (WsStatus.CONNECTED, WsStatus.SUBSCRIBED)

    @property
    def is_degraded(self) -> bool:
        return self._status in (WsStatus.DEGRADED, WsStatus.DISCONNECTED, WsStatus.FAILED)

    @property
    def seconds_since_last_message(self) -> float:
        if self._last_message_at == 0:
            return float("inf")
        return time.monotonic() - self._last_message_at

    def diagnostics(self) -> WsDiagnostics:
        sock = getattr(self._ws, "sock", None)
        connected = bool(sock is not None and getattr(sock, "connected", False))
        return WsDiagnostics(
            status=str(self._status),
            websocket_client_available=_WEBSOCKET_AVAILABLE,
            connected=connected,
            healthy=self.is_healthy,
            degraded=self.is_degraded,
            subscriptions=len(self._subscriptions),
            messages_received=self._messages_received,
            messages_dropped=self._messages_dropped,
            errors=self._errors,
            reconnect_count=self._reconnect_count,
            last_error=self._last_error,
            seconds_since_last_message=self.seconds_since_last_message,
            last_message_at_ms=self._last_message_at_ms,
            queue_size=self._message_queue.qsize(),
        )

    def subscribe_markets(self) -> None:
        self._subscriptions[self.CHANNEL_MARKETS] = {
            "type": "subscribe",
            "channel": self.CHANNEL_MARKETS,
            "batched": True,
        }
        self._send_subscription(self.CHANNEL_MARKETS)

    def subscribe_trades(self, market_id: str) -> None:
        key = f"{self.CHANNEL_TRADES}:{market_id}"
        self._subscriptions[key] = {
            "type": "subscribe",
            "channel": self.CHANNEL_TRADES,
            "id": market_id,
            "batched": True,
        }
        self._send_subscription(key)

    def subscribe_top_trade_markets(self, markets: Optional[list[str]] = None, limit: int = 5) -> list[str]:
        """Subscribe read-only trade streams for the most important markets first."""
        selected = list(markets or DEFAULT_TOP_TRADE_MARKETS)[: max(0, int(limit or 0))]
        subscribed: list[str] = []
        for market_id in selected:
            if not market_id:
                continue
            self.subscribe_trades(str(market_id))
            subscribed.append(str(market_id))
        return subscribed

    def subscribe_orderbook(self, market_id: str) -> None:
        key = f"{self.CHANNEL_ORDERBOOK}:{market_id}"
        self._subscriptions[key] = {
            "type": "subscribe",
            "channel": self.CHANNEL_ORDERBOOK,
            "id": market_id,
            "batched": True,
        }
        self._send_subscription(key)

    def subscribe_subaccount(self, address: str, subaccount_number: int = 0) -> None:
        sub_id = f"{address}/{int(subaccount_number or 0)}"
        key = f"{self.CHANNEL_SUBACCOUNTS}:{sub_id}"
        self._subscriptions[key] = {
            "type": "subscribe",
            "channel": self.CHANNEL_SUBACCOUNTS,
            "id": sub_id,
        }
        self._send_subscription(key)

    def unsubscribe_subaccount(self, address: str, subaccount_number: int = 0) -> None:
        sub_id = f"{address}/{int(subaccount_number or 0)}"
        key = f"{self.CHANNEL_SUBACCOUNTS}:{sub_id}"
        self._subscriptions.pop(key, None)
        self._send_raw({"type": "unsubscribe", "channel": self.CHANNEL_SUBACCOUNTS, "id": sub_id})

    def get_message(self, timeout_s: float = 1.0) -> Optional[WsMessage]:
        try:
            return self._message_queue.get(timeout=timeout_s)
        except Empty:
            return None

    def start(self) -> None:
        if not _WEBSOCKET_AVAILABLE:
            logger.error("websocket-client non disponible — WS désactivé")
            self._status = WsStatus.FAILED
            self._last_error = "websocket-client package missing"
            self._errors += 1
            return

        if self._thread is not None and self._thread.is_alive():
            logger.debug("dYdX WS client déjà démarré: %s", self.ws_url)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="dydx-ws-client")
        self._thread.start()
        logger.info("dYdX WS client démarré: %s", self.ws_url)

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        self._status = WsStatus.DISCONNECTED
        logger.info("dYdX WS client arrêté")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._status = WsStatus.CONNECTING
                self._reconnect_count += 1
                if self._reconnect_count > self.max_reconnect_attempts:
                    logger.error("Max reconnect attempts (%d) atteint — WS FAILED", self.max_reconnect_attempts)
                    self._status = WsStatus.FAILED
                    self._last_error = "max reconnect attempts reached"
                    return

                ws = _ws_lib.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_raw_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_ping=self._on_ping,
                    on_pong=self._on_pong,
                )
                self._ws = ws
                ws.run_forever(ping_interval=int(self.ping_interval_s), ping_timeout=10)
            except Exception as e:
                self._errors += 1
                self._last_error = str(e)
                logger.error("WS run_forever exception: %s", e)

            if self._stop_event.is_set():
                break
            self._status = WsStatus.DEGRADED
            wait = self.reconnect_delay_s * min(self._reconnect_count, 8)
            logger.info("WS reconnect dans %.1fs (tentative %d/%d)", wait, self._reconnect_count, self.max_reconnect_attempts)
            time.sleep(wait)

    def _on_open(self, ws: Any) -> None:
        self._status = WsStatus.CONNECTED
        self._reconnect_count = 0
        self._last_message_at = time.monotonic()
        self._last_message_at_ms = int(time.time() * 1000)
        logger.info("dYdX WS connecté: %s", self.ws_url)
        for key in list(self._subscriptions.keys()):
            self._send_subscription(key)

    def _on_raw_message(self, ws: Any, raw: str) -> None:
        self._last_message_at = time.monotonic()
        self._last_message_at_ms = int(time.time() * 1000)
        self._messages_received += 1
        try:
            data = json.loads(raw)
            channel = data.get("channel", "")
            msg_type = data.get("type", "")
            msg_id = data.get("id")
            contents = data.get("contents", {}) or data.get("data", {})

            msg = WsMessage(
                channel=channel,
                type=msg_type,
                id=msg_id,
                data=contents if isinstance(contents, dict) else {"items": contents},
                received_at_ms=self._last_message_at_ms,
                raw=raw,
            )

            seq = data.get("message_id") or data.get("messageId") or data.get("sequence")
            if seq and channel:
                try:
                    seq_int = int(seq)
                except (TypeError, ValueError):
                    seq_int = None
                key = f"{channel}:{msg_id or ''}"
                last = self._last_sequence.get(key)
                if seq_int is not None and last is not None and seq_int > last + 1:
                    gap = seq_int - last - 1
                    logger.warning("GAP DÉTECTÉ: channel=%s id=%s gap=%d (last=%d current=%d)", channel, msg_id, gap, last, seq_int)
                    if self._on_gap_cb:
                        self._on_gap_cb(channel, str(msg_id or ""))
                if seq_int is not None:
                    self._last_sequence[key] = seq_int

            if msg_type == "subscribed":
                self._status = WsStatus.SUBSCRIBED
            elif msg_type == "error":
                self._errors += 1
                self._last_error = str(contents)[:500]
                self._status = WsStatus.DEGRADED

            try:
                self._message_queue.put_nowait(msg)
            except Exception:
                self._messages_dropped += 1

            if self._on_message_cb:
                self._on_message_cb(msg)
        except Exception as e:
            self._errors += 1
            self._last_error = str(e)
            logger.error("WS message parse error: %s | raw=%s...", e, raw[:200])

    def _on_error(self, ws: Any, error: Exception) -> None:
        self._errors += 1
        self._last_error = str(error)
        logger.error("dYdX WS error: %s", error)
        self._status = WsStatus.DEGRADED

    def _on_close(self, ws: Any, close_status_code: Any, close_msg: Any) -> None:
        logger.info("dYdX WS fermé: code=%s msg=%s", close_status_code, close_msg)
        self._status = WsStatus.DISCONNECTED

    def _on_ping(self, ws: Any, message: bytes) -> None:
        self._last_message_at = time.monotonic()
        self._last_message_at_ms = int(time.time() * 1000)

    def _on_pong(self, ws: Any, message: bytes) -> None:
        self._last_message_at = time.monotonic()
        self._last_message_at_ms = int(time.time() * 1000)

    def _send_subscription(self, key: str) -> None:
        payload = self._subscriptions.get(key)
        if payload:
            self._send_raw(payload, log_key=key)

    def _send_raw(self, payload: dict[str, Any], log_key: str | None = None) -> None:
        if not self._can_send():
            return
        try:
            with self._send_lock:
                if self.subscription_min_interval_s > 0:
                    now = time.monotonic()
                    wait = self.subscription_min_interval_s - (now - self._last_subscription_send)
                    if wait > 0:
                        time.sleep(wait)
                    self._last_subscription_send = time.monotonic()
                self._ws.send(json.dumps(payload))
                self._subscriptions_sent += 1
            logger.debug("WS sent: %s", log_key or payload.get("type"))
        except Exception as e:
            self._errors += 1
            self._last_error = str(e)
            logger.warning("WS send failure: %s", e)
            self._status = WsStatus.DEGRADED

    def _can_send(self) -> bool:
        if not self._ws or self._status not in (WsStatus.CONNECTED, WsStatus.SUBSCRIBED):
            return False
        sock = getattr(self._ws, "sock", None)
        if sock is not None and getattr(sock, "connected", False) is False:
            return False
        return True


__all__ = ["DEFAULT_TOP_TRADE_MARKETS", "DydxIndexerWsClient", "WsDiagnostics", "WsMessage", "WsStatus"]
