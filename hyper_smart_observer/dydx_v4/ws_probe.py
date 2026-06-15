"""Read-only dYdX WebSocket probe.

Usage examples:
    python -m hyper_smart_observer.dydx_v4.ws_probe --channel trades --id BTC-USD --seconds 15
    python -m hyper_smart_observer.dydx_v4.ws_probe --channel markets --seconds 10

No orders, no keys, no wallet signing. This only checks whether the public
Indexer WebSocket connects, subscribes, receives messages, and writes an optional
structured JSONL diagnostic row.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover
    websocket = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

MAINNET_WS = "wss://indexer.dydx.trade/v4/ws"
TESTNET_WS = "wss://indexer.v4testnet.dydx.exchange/v4/ws"
DEFAULT_LOG_PATH = "logs/structured/ws_diagnostics.jsonl"


@dataclass
class ProbeStats:
    connected: bool = False
    subscribed: bool = False
    messages: int = 0
    channel_data: int = 0
    errors: int = 0
    last_type: str = ""
    last_channel: str = ""
    last_error: str = ""
    started_at_ms: int = 0
    finished_at_ms: int = 0
    duration_s: float = 0.0
    url: str = ""
    channel: str = ""
    channel_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": "WS_DIAGNOSTICS",
            "connected": self.connected,
            "subscribed": self.subscribed,
            "messages": self.messages,
            "channel_data": self.channel_data,
            "errors": self.errors,
            "last_type": self.last_type,
            "last_channel": self.last_channel,
            "last_error": self.last_error,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_s": round(self.duration_s, 3),
            "url": self.url,
            "channel": self.channel,
            "id": self.channel_id,
            "healthy": bool(self.connected and self.subscribed and self.errors == 0),
            "live_data": bool(self.channel_data > 0),
            "read_only": True,
            "paper_only": True,
        }


def _payload(channel: str, channel_id: str | None, batched: bool) -> dict[str, Any]:
    mapping = {
        "trades": "v4_trades",
        "markets": "v4_markets",
        "orderbook": "v4_orderbook",
        "subaccounts": "v4_subaccounts",
    }
    ch = mapping.get(channel, channel)
    msg: dict[str, Any] = {"type": "subscribe", "channel": ch}
    if channel_id:
        msg["id"] = channel_id
    if ch in {"v4_trades", "v4_markets", "v4_orderbook"}:
        msg["batched"] = bool(batched)
    return msg


def write_probe_log(stats: ProbeStats, path: str | Path = DEFAULT_LOG_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def run_probe(url: str, channel: str, channel_id: str | None, seconds: float, batched: bool) -> ProbeStats:
    if websocket is None:  # pragma: no cover
        raise RuntimeError(f"websocket-client missing: {_IMPORT_ERROR}")

    stats = ProbeStats(
        started_at_ms=int(time.time() * 1000),
        url=url,
        channel=channel,
        channel_id=str(channel_id or ""),
    )
    started = time.monotonic()
    sub_payload = _payload(channel, channel_id, batched)

    def on_open(ws):
        stats.connected = True
        ws.send(json.dumps(sub_payload))

    def on_message(ws, raw):
        stats.messages += 1
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        stats.last_type = str(data.get("type", ""))
        stats.last_channel = str(data.get("channel", ""))
        if data.get("type") == "subscribed":
            stats.subscribed = True
        if data.get("type") == "channel_data":
            stats.channel_data += 1
        if time.monotonic() - started >= seconds:
            ws.close()

    def on_error(ws, error):
        stats.errors += 1
        stats.last_error = str(error)

    def on_close(ws, code, msg):
        return None

    app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    app.run_forever(ping_interval=30, ping_timeout=10)
    stats.finished_at_ms = int(time.time() * 1000)
    stats.duration_s = time.monotonic() - started
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only dYdX WebSocket probe")
    parser.add_argument("--network", choices=["mainnet", "testnet"], default="mainnet")
    parser.add_argument("--url", default="")
    parser.add_argument("--channel", default="trades", help="trades, markets, orderbook, subaccounts or raw channel")
    parser.add_argument("--id", default="BTC-USD", help="Market id or address/subaccount. Not used for markets.")
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--batched", action="store_true", default=True)
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    url = args.url or (MAINNET_WS if args.network == "mainnet" else TESTNET_WS)
    channel_id = None if args.channel in {"markets", "v4_markets"} else args.id
    stats = run_probe(url, args.channel, channel_id, args.seconds, args.batched)
    if not args.no_log:
        write_probe_log(stats, args.log_path)
    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_LOG_PATH", "MAINNET_WS", "TESTNET_WS", "ProbeStats", "run_probe", "write_probe_log"]
