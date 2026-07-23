"""FLUX userFills LIVE → snapshots frais (rectif Flo 23/07). Cœur PUR, testable sans réseau.

Au lieu d'attendre un snapshot toutes les 300 s, on met à jour la position d'un vault DÈS chaque fill
WS `userFills` : on SEED depuis le dernier snapshot connu (positions par coin), puis on applique chaque
fill (szi += signe×sz). On émet alors un snapshot FRAIS que la détection existante (signaux_vaults)
consomme immédiatement — l'ouverture devient event-driven, et plusieurs petits OPEN/ADD s'AGRÈGENT
naturellement dans la position. Le collecteur réseau (`tools/collecter_userfills_vaults.py`) n'est que
la boucle WS autour de ces fonctions. Lecture seule. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

from typing import Any


def positions_depuis_snapshot(snap: dict) -> dict[str, dict]:
    """{coin: {szi, entryPx}} depuis un snapshot vault (seed de l'état live)."""
    out: dict[str, dict] = {}
    for p in (snap.get("positions") or []):
        c = str(p.get("coin") or "").upper()
        if c:
            out[c] = {"szi": float(p.get("szi") or 0.0), "entryPx": float(p.get("entryPx") or 0.0)}
    return out


def appliquer_fill(positions: dict[str, dict], fill: dict) -> dict[str, dict]:
    """Applique UN fill à l'état des positions (en place) : szi += signe×sz ; met à jour entryPx sur les
    OPEN/ADD (prix du fill). `fill` normalisé : {coin, px, sz, signe}. Rend `positions`."""
    c = str(fill.get("coin") or "").upper()
    if not c:
        return positions
    sz = abs(float(fill.get("sz") or 0.0))
    signe = int(fill.get("signe") or 0)
    px = float(fill.get("px") or 0.0)
    cur = positions.setdefault(c, {"szi": 0.0, "entryPx": px})
    avant = cur["szi"]
    cur["szi"] = round(avant + signe * sz, 10)
    # entryPx suit le prix quand on RENFORCE dans le même sens (OPEN/ADD) ; sinon on garde l'entrée
    if abs(avant) < 1e-12 or (avant > 0) == (signe > 0):
        cur["entryPx"] = px
    if abs(cur["szi"]) < 1e-12:
        cur["szi"] = 0.0
    return positions


def snapshot_depuis_positions(vault: str, positions: dict[str, dict], *, nav_usd: float, ts_ms: int) -> dict:
    """Reconstruit un snapshot vault FRAIS (même format que collecter_vaults) depuis l'état live. On garde
    le NAV du dernier snapshot connu (le NAV bouge lentement ; l'important ici c'est le szi live)."""
    pos = [{"coin": c, "szi": round(v["szi"], 8), "entryPx": v["entryPx"]}
           for c, v in positions.items() if abs(v["szi"]) > 1e-12]
    return {"vault": vault, "ts_ms": int(ts_ms), "nav_usd": float(nav_usd), "positions": pos,
            "n_positions": len(pos), "source": "userfills_live", "read_only": True, "real_execution": False}


def parser_message_userfills(msg: Any, *, vault: str = "") -> list[dict]:
    """Normalise un message WS userFills → fills {coin, px, sz, signe, ts_ms, dir, hash, isSnapshot}.
    `isSnapshot` est propagé (le snapshot initial rejoue l'historique : à IGNORER pour trader). Tolérant."""
    data = msg.get("data") if isinstance(msg, dict) else None
    fills = (data or {}).get("fills") if isinstance(data, dict) else None
    est_snapshot = bool((data or {}).get("isSnapshot")) if isinstance(data, dict) else False
    out: list[dict] = []
    for f in (fills or []):
        try:
            coin = str(f["coin"]).upper()
            px = float(f["px"])
            sz = abs(float(f["sz"]))
            ts = int(f["time"])
        except (KeyError, TypeError, ValueError):
            continue
        side = str(f.get("side") or "").upper()
        try:
            start_pos = float(f.get("startPosition"))
        except (TypeError, ValueError):
            start_pos = None
        out.append({"vault": vault, "coin": coin, "px": px, "sz": sz,
                    "signe": 1 if side == "B" else (-1 if side == "A" else 0),
                    "ts_ms": ts, "dir": str(f.get("dir") or ""), "hash": f.get("hash"),
                    "start_position": start_pos, "isSnapshot": est_snapshot,
                    "source": "LIVE_WS"})                          # PROVENANCE : seuls les vrais fills WS sont tradables
    return out


__all__ = ["positions_depuis_snapshot", "appliquer_fill", "snapshot_depuis_positions",
           "parser_message_userfills"]
