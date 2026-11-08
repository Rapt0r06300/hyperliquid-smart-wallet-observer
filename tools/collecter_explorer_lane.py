#!/usr/bin/env python3
"""Collecteur du FEED EXPLORER Hyperliquid (hors cap 10 users) — idées #1-#10.

Le feed explorer ``wss://rpc.hyperliquid.xyz/ws`` diffuse TOUTES les transactions
on-chain (``explorerTxs`` : user, action, block, hash, time) et les blocs
(``explorerBlock`` : height, blockTime, hash, numTxs, proposer), **sans filtre par
user** : il n'est donc PAS soumis au plafond de 10 users des souscriptions WS
``userFills``. On s'en sert pour :

- **couverture d'activité** de TOUS les leaders (qui place un ordre, quand, quel bloc) ;
- **découverte** de nouveaux leaders actifs (hors whitelist) ;
- **anticipation** des fills (l'action ``order`` précède le fill).

Les réponses explorer sont des **tableaux JSON bruts** (pas d'enveloppe channel/data) :
on identifie bloc vs transaction par les champs du 1er élément. PAPER / LECTURE SEULE :
aucun ordre, aucune clé. (Les fills px/sz exacts restent fournis par userFills/node_fills ;
ce collecteur fournit l'ACTIVITÉ causale horodatée + la découverte.)
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

WS_URL = "wss://rpc.hyperliquid.xyz/ws"
OUT_DEFAUT = Path("runtime") / "data" / "explorer_tx_tape.jsonl"
DECOUVERTE_DEFAUT = Path("runtime") / "data" / "explorer_users_decouverts.json"
SOURCE_ID = "hyperliquid_explorer_txs"


# --------------------------------------------------------------------------- #
# Cœur PUR (testable)
# --------------------------------------------------------------------------- #

def est_bloc(element: Any) -> bool:
    """Un élément du tableau explorer est un BLOC (vs une transaction) ?"""
    return isinstance(element, dict) and (
        "height" in element or "numTxs" in element or "proposer" in element
    )


def parser_tx(tx: Any, *, now_ms: int) -> dict[str, Any] | None:
    """Normalise une transaction explorer. None si inexploitable.

    Champs explorer : ``user``, ``action``, ``block``, ``hash``, ``time``, ``error``.
    Pour une action ``order``, on conserve la liste d'ordres (niveau asset) brute.
    """
    if not isinstance(tx, dict):
        return None
    user = str(tx.get("user") or "").strip().lower()
    if not user.startswith("0x") or len(user) < 10:
        return None
    action = tx.get("action")
    if isinstance(action, dict):
        a_type = str(action.get("type") or "?")
    elif isinstance(action, str):
        a_type = action[:48]
    else:
        a_type = "?"
    rec: dict[str, Any] = {
        "user": user,
        "action_type": a_type,
        "block": tx.get("block"),
        "hash": tx.get("hash"),
        "time": tx.get("time"),
        "error": tx.get("error"),
        "observed_at_ms": int(now_ms),
        "source": "EXPLORER_TX",
        "source_id": SOURCE_ID,
    }
    if isinstance(action, dict) and a_type == "order" and isinstance(action.get("orders"), list):
        rec["orders"] = action["orders"]       # [{a:asset, b:isBuy, p:px, s:sz, ...}]
    return rec


def est_action_trading(rec: dict[str, Any]) -> bool:
    """L'action correspond-elle à une activité de trading (ordre / TWAP / cancel) ?"""
    return rec.get("action_type") in {
        "order", "batchModify", "modify", "twapOrder", "cancel", "cancelByCloid",
        "scheduleCancel",
    }


# --------------------------------------------------------------------------- #
# Collecte (async)
# --------------------------------------------------------------------------- #

class CollecteExplorer:
    def __init__(self, out_path: Path, decouverte_path: Path, *, leaders: set[str] | None,
                 trading_seulement: bool) -> None:
        self.out_path = out_path
        self.decouverte_path = decouverte_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.leaders = leaders            # None = tous les users ; sinon filtre
        self.trading_seulement = trading_seulement
        self._lock = asyncio.Lock()
        self._vus_hash: set[str] = set()
        self.ecrits = 0
        self.blocs = 0
        self.reconnects = 0
        self.users_actifs: dict[str, int] = {}   # user -> nb d'actions vues (découverte)

    async def traiter_message(self, elements: list, now_ms: int) -> None:
        if not isinstance(elements, list):
            return
        if elements and est_bloc(elements[0]):
            self.blocs += len(elements)
            return
        lignes: list[str] = []
        for tx in elements:
            rec = parser_tx(tx, now_ms=now_ms)
            if rec is None:
                continue
            if self.leaders is not None and rec["user"] not in self.leaders:
                # on compte quand meme pour la decouverte, mais on n'ecrit pas
                self.users_actifs[rec["user"]] = self.users_actifs.get(rec["user"], 0) + 1
                continue
            if self.trading_seulement and not est_action_trading(rec):
                continue
            h = rec.get("hash")
            if isinstance(h, str):
                if h in self._vus_hash:
                    continue
                self._vus_hash.add(h)
            self.users_actifs[rec["user"]] = self.users_actifs.get(rec["user"], 0) + 1
            lignes.append(json.dumps(rec, ensure_ascii=False))
        if lignes:
            async with self._lock:
                with self.out_path.open("a", encoding="utf-8") as h2:
                    h2.write("\n".join(lignes) + "\n")
                self.ecrits += len(lignes)

    def ecrire_decouverte(self) -> None:
        top = dict(sorted(self.users_actifs.items(), key=lambda kv: -kv[1])[:500])
        payload = {"schema": "hypersmart.explorer_users.v1", "genere_ms": int(time.time() * 1000),
                   "n_users_vus": len(self.users_actifs), "top_actifs": top}
        try:
            self.decouverte_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        except OSError:
            pass


async def _boucle_ws(c: CollecteExplorer, deadline: float) -> None:
    import websockets

    serie = 0
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 23,
                                          compression="deflate") as ws:
                serie += 1
                for t in ("explorerTxs", "explorerBlock"):
                    await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": t}}))
                    await asyncio.sleep(0.2)
                print(f"[explorer] souscrit explorerTxs + explorerBlock (serie {serie})", flush=True)
                while time.monotonic() < deadline:
                    reste = max(0.0, deadline - time.monotonic())
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=min(20.0, reste or 1.0))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            return
                        continue
                    now_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    # feed explorer = tableaux bruts ; tolère aussi une enveloppe {data:[...]}
                    if isinstance(msg, dict):
                        msg = msg.get("data") if isinstance(msg.get("data"), list) else None
                    if isinstance(msg, list):
                        await c.traiter_message(msg, now_ms)
        except Exception as exc:  # noqa: BLE001 (reconnexion résiliente)
            c.reconnects += 1
            print(f"[explorer] reconnexion ({type(exc).__name__})", flush=True)
            await asyncio.sleep(min(5.0, 1.0 + c.reconnects * 0.5))


def _charger_leaders(root: Path, chemin: str | None) -> set[str] | None:
    if not chemin:
        return None
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    vaults = data.get("vaults") if isinstance(data, dict) else data
    if not isinstance(vaults, list):
        return None
    return {str(v).strip().lower() for v in vaults if str(v).strip().lower().startswith("0x")}


async def _boucle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    leaders = _charger_leaders(root, args.leaders_file) if args.leaders_file else None
    out = Path(args.out) if args.out else (root / OUT_DEFAUT)
    out = out if out.is_absolute() else root / out
    dec = root / DECOUVERTE_DEFAUT
    c = CollecteExplorer(out, dec, leaders=leaders, trading_seulement=not args.toutes_actions)
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    portee = f"{len(leaders)} leaders filtres" if leaders else "TOUS les users (decouverte)"
    print(f"[explorer] collecte {int(args.duree_s)}s · {portee} · "
          f"{'toutes actions' if args.toutes_actions else 'trading seulement'}", flush=True)
    await _boucle_ws(c, deadline)
    c.ecrire_decouverte()
    print(f"[explorer] fini : {c.ecrits} tx ecrites, {c.blocs} blocs vus, "
          f"{len(c.users_actifs)} users distincts, {c.reconnects} reconnexions -> {out}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur feed explorer Hyperliquid (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders-file", default="", help="filtre sur ces leaders (vide = tous)")
    p.add_argument("--toutes-actions", action="store_true", help="garder toutes les actions (pas que trading)")
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
