#!/usr/bin/env python3
"""Collecteur WS userFills LÉGER pour LANE multi-IP (capacité ×N de fills LIVE_WS).

Cap Hyperliquid = ~5 userFills/connexion et ≤10 users uniques/IP. Pour collecter PLUS
de fills live, on fait tourner CE collecteur sur plusieurs IP (runners GitHub) : chaque
lane suit une TRANCHE DISJOINTE des leaders (``--shard-index``/``--shard-count``), en
WS temps réel. Autonome (aucun mutex/cohorte/rotation du gros collecteur), time-boxé,
pensé pour un runner.

Discipline causale STRICTE (comme le poll forward) :
- 1re observation d'un user = SNAPSHOT (``isSnapshot=true``) → fixe le high-water, n'émet
  AUCUN fill (préexistants) ;
- messages suivants (``isSnapshot=false``) → n'émet que les fills STRICTEMENT nouveaux
  (``ts_ms`` > high-water), estampillés à l'instant RÉEL de réception (``observed_at_ms``),
  source ``LIVE_WS``.
Au reconnect : gap-fill REST ``userFillsByTime`` sur la fenêtre de coupure (zéro trou),
dédupliqué par identité (partagé avec le poll).

LECTURE SEULE / PAPER : aucune clé, aucun ordre, aucune signature.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402
from hl_observer.collection.userfills_resilience import (  # noqa: E402
    DedupFills, fenetre_gapfill,
)
from hl_observer.collection.forward_poll_fills import shard_leaders  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
REST_URL = "https://api.hyperliquid.xyz/info"
SOURCE_ID = "hyperliquid_public_userfills"
OUT_DEFAUT = Path("runtime") / "data" / "vault_fills_ws_lane.jsonl"
DEFAULT_LEADERS_FILE = "config/copy_vault_leaders.json"
SUBS_PAR_CONNEXION = 5           # HL cape ~5 userFills/connexion
MAX_USERS_IP = 10                # HL cape ~10 users uniques/IP


# --------------------------------------------------------------------------- #
# Cœur PUR (testable) : discipline causale forward
# --------------------------------------------------------------------------- #

def filtrer_forward(fills: list[dict[str, Any]], high_water_ms: int | None) -> tuple[list[dict[str, Any]], int | None]:
    """Garde les fills STRICTEMENT nouveaux (ts_ms > high-water) et renvoie le
    nouveau high-water. Jamais d'émission d'un fill <= high-water (anti-doublon causal).
    """
    nouveaux: list[dict[str, Any]] = []
    hw = high_water_ms
    for f in fills:
        ts = f.get("ts_ms")
        if not isinstance(ts, int):
            continue
        if high_water_ms is None or ts > high_water_ms:
            nouveaux.append(f)
        hw = ts if hw is None else max(hw, ts)
    return nouveaux, hw


def high_water_snapshot(fills: list[dict[str, Any]], now_ms: int) -> int:
    """High-water d'amorçage depuis un snapshot : max(ts) des fills, sinon maintenant."""
    tss = [f["ts_ms"] for f in fills if isinstance(f.get("ts_ms"), int)]
    return max(tss) if tss else int(now_ms)


# --------------------------------------------------------------------------- #
# REST (gap-fill) — lecture seule
# --------------------------------------------------------------------------- #

def _rest_userfills(user: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    corps = json.dumps({"type": "userFillsByTime", "user": user,
                        "startTime": int(start_ms), "endTime": int(end_ms)}).encode("utf-8")
    req = urllib.request.Request(REST_URL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        data = json.loads(rep.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def _normaliser(message_data: dict[str, Any], *, user: str, received_at_ms: int,
                recv_mono_ns: int | None, connection_id: str) -> list[dict[str, Any]]:
    """Enveloppe des fills (WS ou REST) dans le format attendu par le parser pur."""
    msg = {"channel": "userFills", "data": message_data}
    return parser_message_userfills(
        msg, vault=user, received_at_ms=received_at_ms,
        receive_mono_ns=recv_mono_ns, connection_id=connection_id,
    )


class LaneWS:
    """État partagé d'une lane : écriture, dédup, high-water par user, compteurs."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.dedup = DedupFills(capacite=300_000)
        self.high_water: dict[str, int] = {}
        self.seeded: set[str] = set()
        self._lock = asyncio.Lock()
        self.emis = 0
        self.reconnects = 0
        self.gapfills = 0

    async def emettre(self, fills: list[dict[str, Any]], *, observed_at_ms: int) -> None:
        if not fills:
            return
        nouveaux = self.dedup.filtrer_nouveaux(fills)
        if not nouveaux:
            return
        async with self._lock:
            with self.out_path.open("a", encoding="utf-8") as h:
                for f in nouveaux:
                    f = {**f, "source": "LIVE_WS", "is_snapshot": False,
                         "observed_at_ms": observed_at_ms, "source_id": SOURCE_ID}
                    h.write(json.dumps(f, ensure_ascii=False) + "\n")
            self.emis += len(nouveaux)

    async def gap_fill(self, users: list[str], *, now_ms: int) -> None:
        """Rattrape par REST la fenêtre manquée pour chaque user de la connexion."""
        for user in users:
            fen = fenetre_gapfill(self.high_water.get(user.lower()), now_ms)
            if fen is None:
                continue
            start, end = fen
            try:
                bruts = await asyncio.to_thread(_rest_userfills, user, start, end)
            except Exception as exc:  # noqa: BLE001 (gap-fill résilient)
                print(f"[ws-lane] gap-fill {user[:10]} erreur {type(exc).__name__}", flush=True)
                continue
            parsed = _normaliser({"user": user, "isSnapshot": False, "fills": bruts},
                                 user=user, received_at_ms=now_ms, recv_mono_ns=None,
                                 connection_id=f"gapfill-{user[:8]}")
            nouveaux, hw = filtrer_forward(parsed, self.high_water.get(user.lower()))
            if hw is not None:
                self.high_water[user.lower()] = hw
            await self.emettre(nouveaux, observed_at_ms=now_ms)
            self.gapfills += len(nouveaux)


async def _connexion(lane: LaneWS, users: list[str], socket_id: str, deadline: float) -> None:
    """Une connexion WS pour un groupe de ≤5 users. Reconnexion + gap-fill bornés."""
    import websockets

    connus = {v.lower(): v for v in users}
    serie = 0
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                serie += 1
                connection_id = f"ws-lane-{socket_id}-{int(time.time()*1000)}-{serie}"
                for v in users:
                    await ws.send(json.dumps({"method": "subscribe",
                                              "subscription": {"type": "userFills", "user": v}}))
                    await asyncio.sleep(0.3)   # throttle anti-drop HL
                print(f"[ws-lane] socket {socket_id} : {len(users)} userFills souscrits", flush=True)
                while time.monotonic() < deadline:
                    reste = max(0.0, deadline - time.monotonic())
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=min(30.0, reste or 1.0))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            return
                        continue
                    recv_mono_ns = time.monotonic_ns()
                    recv_wall_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("channel") == "subscriptionResponse":
                        continue  # ACK (confirmation)
                    data = msg.get("data")
                    if msg.get("channel") != "userFills" or not isinstance(data, dict):
                        continue
                    user = str(data.get("user") or "")
                    ucle = user.lower()
                    if ucle not in connus:
                        continue
                    parsed = parser_message_userfills(
                        msg, vault=user, received_at_ms=recv_wall_ms,
                        receive_mono_ns=recv_mono_ns, connection_id=connection_id,
                    )
                    if data.get("isSnapshot") is True or ucle not in lane.seeded:
                        # snapshot d'amorçage : fixe le high-water, n'émet rien de causal
                        lane.high_water[ucle] = high_water_snapshot(parsed, recv_wall_ms)
                        lane.seeded.add(ucle)
                        continue
                    nouveaux, hw = filtrer_forward(parsed, lane.high_water.get(ucle))
                    if hw is not None:
                        lane.high_water[ucle] = hw
                    await lane.emettre(nouveaux, observed_at_ms=recv_wall_ms)
        except Exception as exc:  # noqa: BLE001 (reconnexion résiliente)
            lane.reconnects += 1
            print(f"[ws-lane] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
            await lane.gap_fill(users, now_ms=int(time.time() * 1000))
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
    lane_leaders = shard_leaders(tous, args.shard_count, args.shard_index)
    lane_leaders = lane_leaders[: max(1, int(args.max_users))]
    if not lane_leaders:
        print("[ws-lane] aucun leader pour cette lane.", flush=True)
        return 0
    out = Path(args.out) if args.out else (root / OUT_DEFAUT)
    lane = LaneWS(out if out.is_absolute() else root / out)
    # groupes de ≤ subs-par-connexion users = une connexion WS chacun
    pas = max(1, int(args.subs_par_connexion))
    groupes = [lane_leaders[i:i + pas] for i in range(0, len(lane_leaders), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[ws-lane] lane {args.shard_index}/{args.shard_count} : {len(lane_leaders)} leaders "
          f"sur {len(groupes)} connexion(s), {int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, grp, chr(65 + i), deadline))
              for i, grp in enumerate(groupes)]
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[ws-lane] fini : {lane.emis} fills LIVE_WS emis, {lane.gapfills} par gap-fill, "
          f"{lane.reconnects} reconnexions -> {lane.out_path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur WS userFills léger pour lane multi-IP (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders-file", default=DEFAULT_LEADERS_FILE)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--max-users", type=int, default=MAX_USERS_IP)
    p.add_argument("--subs-par-connexion", type=int, default=SUBS_PAR_CONNEXION)
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
