#!/usr/bin/env python3
"""Collecteur WS L2 (l2Book) LÉGER pour LANE multi-IP — plus de carnets causaux.

Le labo apparie chaque fill a un carnet L2 observe a <=30 s. Plus on couvre de coins
(ceux que les leaders tradent), plus de fills deviennent scoreables -> LCB qui monte.
Hyperliquid pousse l2Book en continu (non cap par user). On repartit les coins en
TRANCHES DISJOINTES par lane (--shard-index), chaque lane sur une IP (runner GitHub).

Discipline causale : on garde chaque carnet observe (received >= exchange, lag <= borne,
niveaux ordonnes/non croises), estampille a l'instant reel de reception. Dedup par
(coin, exchange_ts). Schema ``hypersmart.copy_vault_l2.v1`` = celui que le labo/coffre lit.

LECTURE SEULE / PAPER : aucune cle, aucun ordre.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.datasets.coffre_certifie import certifier_book, QUARANTAINE  # noqa: E402
from hl_observer.collection.forward_poll_fills import shard_leaders  # noqa: E402 (shard generique)

WS_URL = "wss://api.hyperliquid.xyz/ws"
OUT_DEFAUT = Path("runtime") / "data" / "copy_vault_l2_lane.jsonl"
BBO_OUT_DEFAUT = Path("runtime") / "data" / "copy_vault_bbo_lane.jsonl"
DEFAULT_COINS_FILE = "config/copy_vault_coins.json"
COINS_PAR_CONNEXION = 40          # l2Book non cap par user ; on groupe pour limiter les connexions
LAG_MAX_MS = 30_000               # fraîcheur causale (aligné sur le labo MAX_TARGET_LAG_MS)
GAP_L2_MS = 15_000                # B6 : au-delà, un coin silencieux compte comme un trou L2


def _nb(v):
    try:
        import math
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def construire_bbo(data: Any, *, recv_ms: int) -> tuple[dict[str, Any] | None, str]:
    """Construit un top-of-book BBO (schema ``hypersmart.copy_vault_bbo.v1``) depuis
    une frame HL l2Book, pour nourrir le REPLI BBO du labo (apparie plus de fills
    quand le L2 complet manque). Validation causale : received >= exchange, lag borné,
    non croisé, positif. Renvoie (row|None, raison).
    """
    if not isinstance(data, dict):
        return None, "frame_invalide"
    coin = data.get("coin")
    exch = data.get("time")
    niveaux = data.get("levels")
    if not isinstance(niveaux, list) or len(niveaux) != 2:
        return None, "niveaux_absents"

    def top(side):
        if isinstance(side, list) and side:
            e = side[0]
            if isinstance(e, dict):
                return _nb(e.get("px")), _nb(e.get("sz"))
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                return _nb(e[0]), _nb(e[1])
        return None, None

    bid_px, bid_sz = top(niveaux[0])
    ask_px, ask_sz = top(niveaux[1])
    if None in (bid_px, bid_sz, ask_px, ask_sz):
        return None, "cote_vide"
    if not isinstance(exch, int) or exch <= 0:
        return None, "exchange_ts_invalide"
    if not (recv_ms >= exch and recv_ms - exch <= LAG_MAX_MS):
        return None, "lag_causal_depasse"
    if not (bid_px > 0 and ask_px > bid_px and bid_sz > 0 and ask_sz > 0):
        return None, "bbo_invalide_ou_croise"
    from hl_observer.datasets.coffre_certifie import _canonical_coin  # léger
    c = _canonical_coin(coin)
    if not c:
        return None, "coin_absent"
    return {
        "schema_version": "hypersmart.copy_vault_bbo.v1", "coin": c,
        "received_at_ms": int(recv_ms), "exchange_ts_ms": int(exch),
        "bid_px": bid_px, "bid_sz": bid_sz, "ask_px": ask_px, "ask_sz": ask_sz,
        "source": "HYPERLIQUID_BBO_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }, ""


def construire_carnet(data: Any, *, recv_ms: int) -> tuple[dict[str, Any] | None, str]:
    """Construit un carnet v1 depuis une frame HL l2Book, valide via ``certifier_book``.

    Renvoie (row|None, raison). ``data`` = frame.data : {coin, time, levels:[bids, asks]}
    ou chaque niveau est {px, sz, n}.
    """
    if not isinstance(data, dict):
        return None, "frame_invalide"
    coin = data.get("coin")
    exch = data.get("time")
    niveaux = data.get("levels")
    if not isinstance(niveaux, list) or len(niveaux) != 2:
        return None, "niveaux_absents"

    def cinq(side: Any) -> list[list[float]]:
        out: list[list[float]] = []
        if isinstance(side, list):
            for e in side[:5]:
                if isinstance(e, dict) and "px" in e and "sz" in e:
                    out.append([e.get("px"), e.get("sz")])
                elif isinstance(e, (list, tuple)) and len(e) >= 2:
                    out.append([e[0], e[1]])
        return out

    bids5, asks5 = cinq(niveaux[0]), cinq(niveaux[1])
    if not bids5 or not asks5:
        return None, "cote_vide"
    row = {
        "schema_version": "hypersmart.copy_vault_l2.v1", "coin": coin,
        "received_at_ms": recv_ms, "exchange_ts_ms": exch,
        "bid": bids5[0][0], "ask": asks5[0][0], "bids5": bids5, "asks5": asks5,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
    }
    norm, decision, raison = certifier_book(row, source="HYPERLIQUID_L2_WS", now_ms=recv_ms)
    if decision == QUARANTAINE:
        return None, raison
    return norm, ""


class LaneL2:
    def __init__(self, out_path: Path, bbo_out_path: Path) -> None:
        self.out_path = out_path
        self.bbo_out_path = bbo_out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.bbo_out_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._lock_bbo = asyncio.Lock()
        self.dernier_ts: dict[str, int] = {}       # coin -> dernier exchange_ts carnet (dedup)
        self.dernier_ts_bbo: dict[str, int] = {}   # coin -> dernier exchange_ts BBO (dedup)
        self.emis = 0
        self.emis_bbo = 0
        self.rejets = 0
        self.reconnects = 0
        self.gaps = 0        # B6 : trous L2 detectes (coin silencieux > seuil)

    async def ecrire(self, row: dict[str, Any]) -> None:
        coin = str(row.get("coin"))
        exch = int(row.get("exchange_ts_ms") or 0)
        precedent = self.dernier_ts.get(coin, 0)
        if exch <= precedent:
            return  # deja un carnet >= cet instant pour ce coin
        # B6 : detection de trou (le coin est reste silencieux plus longtemps que le seuil).
        if precedent and exch - precedent > GAP_L2_MS:
            self.gaps += 1
        self.dernier_ts[coin] = exch
        async with self._lock:
            with self.out_path.open("a", encoding="utf-8") as h:
                h.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.emis += 1

    async def ecrire_bbo(self, row: dict[str, Any]) -> None:
        coin = str(row.get("coin"))
        exch = int(row.get("exchange_ts_ms") or 0)
        if exch <= self.dernier_ts_bbo.get(coin, 0):
            return
        self.dernier_ts_bbo[coin] = exch
        async with self._lock_bbo:
            with self.bbo_out_path.open("a", encoding="utf-8") as h:
                h.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.emis_bbo += 1


async def _connexion(lane: LaneL2, coins: list[str], socket_id: str, deadline: float) -> None:
    import websockets

    connus = {str(c).upper() for c in coins}
    serie = 0
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22,
                                          compression="deflate") as ws:  # A22 permessage-deflate
                serie += 1
                for c in coins:
                    await ws.send(json.dumps({"method": "subscribe",
                                              "subscription": {"type": "l2Book", "coin": c}}))
                    await asyncio.sleep(0.05)
                print(f"[l2-lane] socket {socket_id} : {len(coins)} l2Book souscrits", flush=True)
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
                    if not isinstance(msg, dict) or msg.get("channel") != "l2Book":
                        continue
                    data = msg.get("data")
                    if not isinstance(data, dict) or str(data.get("coin") or "").upper() not in connus:
                        continue
                    # BBO (top-of-book) : nourrit le repli BBO du labo, meme si le L2
                    # complet est rejete sur ce frame.
                    bbo, _rb = construire_bbo(data, recv_ms=recv_ms)
                    if bbo is not None:
                        await lane.ecrire_bbo(bbo)
                    row, _raison = construire_carnet(data, recv_ms=recv_ms)
                    if row is None:
                        lane.rejets += 1
                        continue
                    await lane.ecrire(row)
        except Exception as exc:  # noqa: BLE001 (reconnexion resiliente)
            lane.reconnects += 1
            print(f"[l2-lane] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
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
        print("[l2-lane] aucun coin pour cette lane.", flush=True)
        return 0
    out = Path(args.out) if args.out else (root / OUT_DEFAUT)
    out = out if out.is_absolute() else root / out
    bbo_out = Path(args.bbo_out) if args.bbo_out else (root / BBO_OUT_DEFAUT)
    bbo_out = bbo_out if bbo_out.is_absolute() else root / bbo_out
    lane = LaneL2(out, bbo_out)
    pas = max(1, int(args.coins_par_connexion))
    groupes = [lane_coins[i:i + pas] for i in range(0, len(lane_coins), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[l2-lane] lane {args.shard_index}/{args.shard_count} : {len(lane_coins)} coins "
          f"sur {len(groupes)} connexion(s), {int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, grp, chr(65 + i), deadline))
              for i, grp in enumerate(groupes)]
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[l2-lane] fini : {lane.emis} carnets L2 + {lane.emis_bbo} BBO emis, "
          f"{lane.rejets} rejets, {lane.reconnects} reconnexions, {lane.gaps} trous L2 "
          f"-> {lane.out_path}", flush=True)
    # B29 : sante JSON de la lane (metriques, sans changer l'affichage console).
    try:
        sante = {"lane": f"{args.shard_index}/{args.shard_count}", "coins": len(lane_coins),
                 "carnets_emis": lane.emis, "bbo_emis": lane.emis_bbo, "rejets": lane.rejets,
                 "reconnects": lane.reconnects, "trous_l2": lane.gaps,
                 "genere_ms": int(time.time() * 1000)}
        (lane.out_path.parent / f"l2_lane_sante_{args.shard_index}.json").write_text(
            json.dumps(sante, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur WS l2Book léger pour lane multi-IP (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--coins-file", default=DEFAULT_COINS_FILE)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--coins-par-connexion", type=int, default=COINS_PAR_CONNEXION)
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--out", default="")
    p.add_argument("--bbo-out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
