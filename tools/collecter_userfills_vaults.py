"""COLLECTEUR WS userFills DES VAULTS (rectif Flo 23/07) — rend l'ouverture EVENT-DRIVEN.

S'abonne au flux WS `userFills` de chaque vault CORE+CHALLENGER, et DÈS chaque fill : met à jour la
position live (seed depuis le dernier snapshot + application du fill), écrit un snapshot FRAIS dans
`vault_snapshots.jsonl` (que signaux_vaults consomme immédiatement) et journalise le fill brut dans
`vault_fills_live.jsonl`. Plusieurs petits OPEN/ADD s'agrègent naturellement dans la position. Le cœur
est dans `hl_observer.collection.userfills_live` (testé). Reconnect + throttle. Lecture seule ; 0 ordre.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import userfills_live as UL  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
SNAP = Path("runtime") / "data" / "vault_snapshots.jsonl"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
THROTTLE_SNAP_S = 2.0             # au plus un snapshot frais / 2 s / vault (évite le spam disque)


def vaults_suivis(root: Path, *, n: int = 8) -> list[str]:
    """CORE + CHALLENGERS : les vaults à suivre en WS (depuis vaults_scores). Deny-by-default : sans
    score, aucun vault (donc aucun abonnement)."""
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    core = [c["vault"] for c in (d.get("classement") or []) if c.get("retenu")][:2]
    autres = [c["vault"] for c in (d.get("classement") or []) if not c.get("retenu")][: n - len(core)]
    return core + autres


def _seed(root: Path, vault: str) -> tuple[dict, float]:
    """(positions live, nav) seed depuis le DERNIER snapshot connu du vault."""
    dernier = None
    try:
        for l in (root / SNAP).read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("vault") == vault:
                dernier = d
    except OSError:
        pass
    if not dernier:
        return {}, 0.0
    return UL.positions_depuis_snapshot(dernier), float(dernier.get("nav_usd") or 0.0)


async def _un_vault(root: Path, vault: str) -> None:
    import websockets  # import tardif (le cœur pur ne dépend pas du réseau)
    positions, nav = _seed(root, vault)
    derniere_ecriture = 0.0
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                await ws.send(json.dumps({"method": "subscribe",
                                          "subscription": {"type": "userFills", "user": vault}}))
                async for brut in ws:
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    fills = UL.parser_message_userfills(msg, vault=vault)
                    if not fills:
                        continue
                    with (root / FILLS_LIVE).open("a", encoding="utf-8") as f:
                        for x in fills:
                            f.write(json.dumps(x, ensure_ascii=False) + "\n")
                    for x in fills:
                        UL.appliquer_fill(positions, x)
                    if time.time() - derniere_ecriture >= THROTTLE_SNAP_S:
                        snap = UL.snapshot_depuis_positions(vault, positions, nav_usd=nav,
                                                            ts_ms=int(time.time() * 1000))
                        with (root / SNAP).open("a", encoding="utf-8") as f:
                            f.write(json.dumps(snap, ensure_ascii=False) + "\n")
                        derniere_ecriture = time.time()
        except Exception as exc:  # noqa: BLE001 — reconnect, on ne meurt pas
            print("[userfills-live] %s reconnect (%s)" % (vault[:10], str(exc)[:50]), flush=True)
            await asyncio.sleep(3.0)


async def _boucle(root: Path) -> None:
    vaults = vaults_suivis(root)
    if not vaults:
        print("[userfills-live] aucun vault suivi (deny-by-default) — rien a faire", flush=True)
        return
    (root / SNAP).parent.mkdir(parents=True, exist_ok=True)
    print("[userfills-live] abonnement userFills WS de %d vaults" % len(vaults), flush=True)
    await asyncio.gather(*[_un_vault(root, v) for v in vaults])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur WS userFills des vaults (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    a = p.parse_args(argv)
    try:
        asyncio.run(_boucle(Path(a.root)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
