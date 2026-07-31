"""CHANTIER #2 — Global Wallet : backfill MASSIF via l'endpoint officiel Hyperliquid node_fills_by_block.

Passe de quelques dizaines de wallets à des MILLIERS en itérant les blocs. Chaque bloc → liste de fills ;
on parse en fill canonique, on DÉDUP (par tid explicite, sinon empreinte user:coin:ts:px:sz), on accumule
l'univers de wallets, on suit la couverture de blocs (trous inclus), et on écrit un JSONL append-only.

`client` doit exposer `fills_by_block(block) -> list[dict]` (adaptateur node/REST côté machine Flo). Sans client
→ BLOCKED_EXTERNAL (aucune donnée fabriquée). 0 réseau ici, 0 ordre réel.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

BLOCKED = "BLOCKED_EXTERNAL"
_LONG = ("B", "BUY", "LONG", "BID", "1", "+1")


class NodeClient(Protocol):
    def fills_by_block(self, block: int) -> Iterable[Mapping[str, Any]]: ...


def _sens(f: Mapping[str, Any]) -> float | None:
    s = str(f.get("side", f.get("dir", ""))).strip().upper()
    if not s:
        return None
    return 1.0 if any(s.startswith(x) for x in _LONG) else -1.0


def fill_canonique(f: Mapping[str, Any], *, block: int) -> dict[str, Any] | None:
    """Parse un fill node → canonique {user, coin, side, px, sz, ts_ms, tid, block, hash}. None si inexploitable."""
    user = f.get("user") or f.get("adresse") or f.get("address")
    coin = f.get("coin")
    if not user or not coin:
        return None
    return {"user": str(user).lower(), "coin": str(coin), "side": _sens(f),
            "px": f.get("px"), "sz": f.get("sz"),
            "ts_ms": f.get("ts_ms", f.get("time")), "tid": f.get("tid"),
            "hash": f.get("hash"), "block": int(block)}


def _cle_dedup(fc: Mapping[str, Any]) -> str:
    if fc.get("tid") is not None:
        return "tid:%s" % fc["tid"]
    return "emp:%s:%s:%s:%s:%s" % (fc["user"], fc["coin"], fc.get("ts_ms"), fc.get("px"), fc.get("sz"))


def backfill(client: NodeClient | None, blocks: Iterable[int], out_path: str) -> dict[str, Any]:
    """Itère les `blocks` via le client node, écrit les fills canoniques dédupliqués, accumule l'univers de
    wallets et la couverture de blocs. Sans client → BLOCKED_EXTERNAL."""
    if client is None:
        return {"statut": BLOCKED, "manque": "client node Hyperliquid (node_fills_by_block) cote user",
                "real_execution": False}
    vus: set[str] = set()
    wallets: set[str] = set()
    blocs_couverts: list[int] = []
    n_fills = 0
    with open(out_path, "a", encoding="utf-8") as fh:
        for b in blocks:
            blocs_couverts.append(int(b))
            for raw in client.fills_by_block(b):
                fc = fill_canonique(raw, block=int(b))
                if fc is None:
                    continue
                cle = _cle_dedup(fc)
                if cle in vus:                            # même fill revu (recouvrement de blocs) -> ignoré
                    continue
                vus.add(cle)
                wallets.add(fc["user"])
                fh.write(json.dumps(fc, ensure_ascii=False) + "\n")
                n_fills += 1
    blocs_couverts.sort()
    trous = [(blocs_couverts[i - 1], blocs_couverts[i]) for i in range(1, len(blocs_couverts))
             if blocs_couverts[i] - blocs_couverts[i - 1] > 1]
    return {"statut": "OK", "n_fills": n_fills, "n_wallets": len(wallets), "n_blocs": len(blocs_couverts),
            "bloc_min": (blocs_couverts[0] if blocs_couverts else None),
            "bloc_max": (blocs_couverts[-1] if blocs_couverts else None),
            "trous_blocs": trous, "real_execution": False}


__all__ = ["NodeClient", "fill_canonique", "backfill", "BLOCKED"]
