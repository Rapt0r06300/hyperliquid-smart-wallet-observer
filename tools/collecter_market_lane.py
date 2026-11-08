#!/usr/bin/env python3
"""Collecteur WS marché public (trades + candle) pour lane multi-IP — idées #22-#23.

Canaux PUBLICS gratuits d'Hyperliquid :
- ``trades`` (par coin) : bande de trades marché → exécution réaliste (fin du « mid = fill »),
  schéma aligné sur la famille ``copy_vault_trades`` du labo.
- ``candle`` (par coin, intervalle) : OHLCV → volatilité réalisée + régimes.

Chaque lane suit une tranche DISJOINTE de coins (``--shard-index``/``--shard-count``).
PAPER / LECTURE SEULE : WS public, aucun ordre, aucune clé.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.forward_poll_fills import shard_leaders  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
TRADES_OUT = Path("runtime") / "data" / "copy_vault_trades_lane.jsonl"
CANDLE_OUT = Path("runtime") / "data" / "copy_vault_candle_lane.jsonl"
DEFAULT_COINS_FILE = "config/copy_vault_coins.json"
COINS_PAR_CONNEXION = 40


def _nb(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def parser_trade(t: Any, *, recv_ms: int) -> dict[str, Any] | None:
    """Normalise un trade public -> schéma aligné `copy_vault_trades`."""
    if not isinstance(t, dict):
        return None
    coin = t.get("coin")
    px, sz = _nb(t.get("px")), _nb(t.get("sz"))
    exch = t.get("time")
    if not coin or px is None or sz is None or px <= 0 or sz <= 0:
        return None
    if not isinstance(exch, int) or exch <= 0 or recv_ms < exch:
        return None
    side = str(t.get("side") or "")
    aggressor = "BUY" if side in ("B", "BUY", "b") else "SELL" if side in ("A", "S", "SELL", "a") else "?"
    return {
        "schema_version": "hypersmart.copy_vault_trades.v1", "coin": str(coin),
        "exchange_ts_ms": int(exch), "received_at_ms": int(recv_ms),
        "price": px, "size": sz, "aggressor_side": aggressor,
        "hash": t.get("hash"), "tid": t.get("tid"),
        "source": "HYPERLIQUID_TRADES_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
    }


def parser_candle(c: Any, *, recv_ms: int) -> dict[str, Any] | None:
    """Normalise une bougie (OHLCV) -> tape candle."""
    if not isinstance(c, dict):
        return None
    coin = c.get("s") or c.get("coin")
    o, h, l, cl = _nb(c.get("o")), _nb(c.get("h")), _nb(c.get("l")), _nb(c.get("c"))
    deb, fin = c.get("t"), c.get("T")
    if not coin or None in (o, h, l, cl) or not isinstance(deb, int):
        return None
    return {
        "schema_version": "hypersmart.copy_vault_candle.v1", "coin": str(coin),
        "interval": c.get("i"), "open_ts_ms": int(deb),
        "close_ts_ms": int(fin) if isinstance(fin, int) else None,
        "open": o, "high": h, "low": l, "close": cl, "volume": _nb(c.get("v")),
        "n_trades": c.get("n"), "received_at_ms": int(recv_ms),
        "source": "HYPERLIQUID_CANDLE_WS", "data_origin": "REAL_OBSERVED",
    }


class LaneMarche:
    def __init__(self, trades_out: Path, candle_out: Path, *, intervalle: str) -> None:
        self.trades_out = trades_out
        self.candle_out = candle_out
        self.intervalle = intervalle
        trades_out.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._vus_trade: set = set()
        self.trades = 0
        self.candles = 0
        self.reconnects = 0

    async def ecrire_trade(self, row: dict[str, Any]) -> None:
        cle = (row.get("coin"), row.get("tid"), row.get("hash"), row.get("exchange_ts_ms"),
               row.get("price"), row.get("size"))
        if cle in self._vus_trade:
            return
        self._vus_trade.add(cle)
        async with self._lock:
            with self.trades_out.open("a", encoding="utf-8") as h:
                h.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.trades += 1

    async def ecrire_candle(self, row: dict[str, Any]) -> None:
        async with self._lock:
            with self.candle_out.open("a", encoding="utf-8") as h:
                h.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.candles += 1


async def _connexion(lane: LaneMarche, coins: list[str], socket_id: str, deadline: float,
                     *, avec_candle: bool) -> None:
    import websockets

    connus = {str(c).upper() for c in coins}
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22,
                                          compression="deflate") as ws:
                for c in coins:
                    await ws.send(json.dumps({"method": "subscribe",
                                              "subscription": {"type": "trades", "coin": c}}))
                    if avec_candle:
                        await ws.send(json.dumps({"method": "subscribe", "subscription":
                                                  {"type": "candle", "coin": c, "interval": lane.intervalle}}))
                    await asyncio.sleep(0.05)
                print(f"[market] socket {socket_id} : {len(coins)} coins (trades"
                      f"{'+candle' if avec_candle else ''})", flush=True)
                while time.monotonic() < deadline:
                    reste = max(0.0, deadline - time.monotonic())
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=min(30.0, reste or 1.0))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            return
                        continue
                    recv_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    canal = msg.get("channel")
                    data = msg.get("data")
                    if canal == "trades" and isinstance(data, list):
                        for t in data:
                            if isinstance(t, dict) and str(t.get("coin") or "").upper() in connus:
                                row = parser_trade(t, recv_ms=recv_ms)
                                if row:
                                    await lane.ecrire_trade(row)
                    elif canal == "candle" and isinstance(data, dict):
                        if str(data.get("s") or data.get("coin") or "").upper() in connus:
                            row = parser_candle(data, recv_ms=recv_ms)
                            if row:
                                await lane.ecrire_candle(row)
        except Exception as exc:  # noqa: BLE001
            lane.reconnects += 1
            print(f"[market] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
            await asyncio.sleep(min(5.0, 1.0 + lane.reconnects * 0.5))


def _charger_coins(root: Path, chemin: str) -> list[str]:
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    coins = data.get("coins") if isinstance(data, dict) else data
    if not isinstance(coins, list):
        return []
    vus: dict[str, None] = {}
    for c in coins:
        s = str(c).strip().upper()
        if s:
            vus.setdefault(s, None)
    return list(vus)


async def _boucle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    tous = _charger_coins(root, args.coins_file)
    lane_coins = shard_leaders(tous, args.shard_count, args.shard_index)
    if not lane_coins:
        print("[market] aucun coin pour cette lane.", flush=True)
        return 0
    trades_out = Path(args.trades_out) if args.trades_out else (root / TRADES_OUT)
    candle_out = Path(args.candle_out) if args.candle_out else (root / CANDLE_OUT)
    trades_out = trades_out if trades_out.is_absolute() else root / trades_out
    candle_out = candle_out if candle_out.is_absolute() else root / candle_out
    lane = LaneMarche(trades_out, candle_out, intervalle=args.intervalle)
    pas = max(1, int(args.coins_par_connexion))
    groupes = [lane_coins[i:i + pas] for i in range(0, len(lane_coins), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[market] lane {args.shard_index}/{args.shard_count} : {len(lane_coins)} coins, "
          f"{int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, g, chr(65 + i), deadline, avec_candle=not args.sans_candle))
              for i, g in enumerate(groupes)]
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[market] fini : {lane.trades} trades + {lane.candles} bougies, "
          f"{lane.reconnects} reconnexions -> {lane.trades_out}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur WS trades+candle public pour lane (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--coins-file", default=DEFAULT_COINS_FILE)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--coins-par-connexion", type=int, default=COINS_PAR_CONNEXION)
    p.add_argument("--intervalle", default="1m")
    p.add_argument("--sans-candle", action="store_true", help="trades seulement")
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--trades-out", default="")
    p.add_argument("--candle-out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
