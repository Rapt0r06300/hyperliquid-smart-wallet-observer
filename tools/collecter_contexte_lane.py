#!/usr/bin/env python3
"""Collecteur WS de CONTEXTE leader (positions + TWAP) — idées #26, #29.

Canaux user (sans signature) d'Hyperliquid, par leader :
- ``clearinghouseState`` : état complet du compte (positions par coin) en push →
  **snapshots de position frais** (le labo seede ses épisodes dessus).
- ``userTwapSliceFills`` : slices de TWAP/metaorders → **anticipation** et densité de fills.

Par-user = soumis au cap 10 users/IP : chaque lane suit une tranche disjointe des
leaders (``--shard-index``/``--shard-count``). PAPER / LECTURE SEULE.
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
POS_OUT = Path("runtime") / "data" / "copy_vault_positions_lane.jsonl"
TWAP_OUT = Path("runtime") / "data" / "copy_vault_twap_lane.jsonl"
DEFAULT_LEADERS_FILE = "config/copy_vault_leaders.json"
USERS_PAR_CONNEXION = 5


def _nb(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def parser_positions(data: Any, *, user: str, recv_ms: int) -> list[dict[str, Any]]:
    """Positions ouvertes depuis un message clearinghouseState."""
    if not isinstance(data, dict):
        return []
    user = str(user or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in data.get("assetPositions") or []:
        pos = item.get("position") if isinstance(item, dict) else None
        if not isinstance(pos, dict) or not pos.get("coin"):
            continue
        szi = _nb(pos.get("szi"))
        if szi is None or szi == 0:  # position plate = pas de position ouverte (bruit pour le seed)
            continue
        out.append({
            "schema_version": "hypersmart.copy_vault_positions.v1", "vault": user,
            "coin": str(pos.get("coin")), "szi": szi, "entry_px": _nb(pos.get("entryPx")),
            "position_value": _nb(pos.get("positionValue")), "unrealized_pnl": _nb(pos.get("unrealizedPnl")),
            "received_at_ms": int(recv_ms), "source": "CLEARINGHOUSE_WS", "data_origin": "REAL_OBSERVED",
        })
    return out


def parser_twap_fills(data: Any, *, user: str, recv_ms: int) -> list[dict[str, Any]]:
    """Fills de slices TWAP → schéma fill (source LIVE_TWAP, causal forward)."""
    if not isinstance(data, dict):
        return []
    user = str(user or "").strip().lower()
    fills = data.get("fills") or data.get("twapSliceFills") or []
    out: list[dict[str, Any]] = []
    for f in fills if isinstance(fills, list) else []:
        if isinstance(f, dict) and isinstance(f.get("fill"), dict):
            f = f["fill"]
        if not isinstance(f, dict):
            continue
        coin = f.get("coin")
        px, sz = _nb(f.get("px")), _nb(f.get("sz"))
        ts = f.get("time")
        if not coin or px is None or sz is None or px <= 0 or sz <= 0 or not isinstance(ts, int):
            continue
        side = str(f.get("side") or "")
        signe = 1 if side in ("B", "b") else -1 if side in ("A", "S", "a") else None
        if signe is None:
            continue
        out.append({
            "vault": user, "coin": str(coin), "px": px, "sz": sz, "signe": signe,
            "ts_ms": int(ts), "observed_at_ms": int(recv_ms), "isSnapshot": False, "is_snapshot": False,
            "hash": f.get("hash"), "tid": f.get("tid"), "oid": f.get("oid"),
            "source": "LIVE_TWAP", "source_id": "hyperliquid_twap_slice_fills",
        })
    return out


class LaneContexte:
    def __init__(self, pos_out: Path, twap_out: Path) -> None:
        self.pos_out = pos_out
        self.twap_out = twap_out
        pos_out.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._vus_twap: set = set()
        self.positions = 0
        self.twap = 0
        self.reconnects = 0

    async def ecrire_positions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._lock:
            with self.pos_out.open("a", encoding="utf-8") as h:
                for r in rows:
                    h.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.positions += len(rows)

    async def ecrire_twap(self, rows: list[dict[str, Any]]) -> None:
        nouveaux = []
        for r in rows:
            cle = (r.get("vault"), r.get("coin"), r.get("ts_ms"), r.get("tid"), r.get("hash"))
            if cle in self._vus_twap:
                continue
            self._vus_twap.add(cle)
            nouveaux.append(r)
        if not nouveaux:
            return
        async with self._lock:
            with self.twap_out.open("a", encoding="utf-8") as h:
                for r in nouveaux:
                    h.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.twap += len(nouveaux)


async def _connexion(lane: LaneContexte, users: list[str], socket_id: str, deadline: float) -> None:
    import websockets

    connus = {v.lower(): v for v in users}
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22,
                                          compression="deflate") as ws:
                for v in users:
                    for t in ("clearinghouseState", "userTwapSliceFills"):
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": t, "user": v}}))
                        await asyncio.sleep(0.2)
                print(f"[contexte] socket {socket_id} : {len(users)} leaders (positions+TWAP)", flush=True)
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
                    if not isinstance(data, dict):
                        continue
                    user = str(data.get("user") or "")
                    if user and user.lower() not in connus:
                        continue
                    if canal == "clearinghouseState":
                        await lane.ecrire_positions(parser_positions(data, user=user, recv_ms=recv_ms))
                    elif canal == "userTwapSliceFills":
                        await lane.ecrire_twap(parser_twap_fills(data, user=user, recv_ms=recv_ms))
        except Exception as exc:  # noqa: BLE001
            lane.reconnects += 1
            print(f"[contexte] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
            await asyncio.sleep(min(5.0, 1.0 + lane.reconnects * 0.5))


def _charger_leaders(root: Path, chemin: str) -> list[str]:
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    vaults = data.get("vaults") if isinstance(data, dict) else data
    if not isinstance(vaults, list):
        return []
    vus: dict[str, None] = {}
    for v in vaults:
        s = str(v).strip()
        if s.lower().startswith("0x") and len(s) >= 10:
            vus.setdefault(s, None)
    return list(vus)


async def _boucle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    tous = _charger_leaders(root, args.leaders_file)
    lane_leaders = shard_leaders(tous, args.shard_count, args.shard_index)[: max(1, int(args.max_users))]
    if not lane_leaders:
        print("[contexte] aucun leader pour cette lane.", flush=True)
        return 0
    pos_out = (root / POS_OUT) if not args.pos_out else Path(args.pos_out)
    twap_out = (root / TWAP_OUT) if not args.twap_out else Path(args.twap_out)
    pos_out = pos_out if pos_out.is_absolute() else root / pos_out
    twap_out = twap_out if twap_out.is_absolute() else root / twap_out
    lane = LaneContexte(pos_out, twap_out)
    pas = max(1, int(args.users_par_connexion))
    groupes = [lane_leaders[i:i + pas] for i in range(0, len(lane_leaders), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[contexte] lane {args.shard_index}/{args.shard_count} : {len(lane_leaders)} leaders, "
          f"{int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, g, chr(65 + i), deadline))
              for i, g in enumerate(groupes)]
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[contexte] fini : {lane.positions} snapshots positions + {lane.twap} TWAP fills, "
          f"{lane.reconnects} reconnexions.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur contexte leader (positions+TWAP), lecture seule.")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders-file", default=DEFAULT_LEADERS_FILE)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--max-users", type=int, default=10)
    p.add_argument("--users-par-connexion", type=int, default=USERS_PAR_CONNEXION)
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--pos-out", default="")
    p.add_argument("--twap-out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
