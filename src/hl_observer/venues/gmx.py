"""[DATA-090..093 / AUD-282] Adaptateur GMX (perp Arbitrum/Avalanche, subgraph) — OFFLINE :
normalisation de records documentes (positions, trades, performance) vers le schema canonique + registre
d'entites et agregation de performance par compte (copy-trading). Pull LIVE (subgraph The Graph) derriere
REQUIRES_NETWORK. Normalizers DEFENSIFS. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_NETWORK, ligne, to_float

VENUE = "gmx"
ENDPOINTS = {
    "subgraph_arbitrum": "https://subgraph.satsuma-prod.com/gmx/synthetics-arbitrum",
    "entities": ("positions", "trades", "accountPerformance"),
}


def _premier(d: Mapping, *cles):
    for k in cles:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _side_from_islong(rec: Mapping):
    v = _premier(rec, "isLong", "long")
    if v is None:
        return _premier(rec, "side", "direction")
    return "buy" if v in (True, "true", 1, "1") else "sell"


def normalize_position(p: Mapping) -> dict:
    """position : account, market/indexToken, isLong, sizeInUsd, collateralAmount."""
    return {"venue": VENUE, "wallet": _premier(p, "account", "wallet"),
            "symbole": _premier(p, "market", "indexToken", "symbol"),
            "side": _side_from_islong(p),
            "taille_usd": to_float(_premier(p, "sizeInUsd", "size", "sizeUsd")),
            "collateral": to_float(_premier(p, "collateralAmount", "collateral"))}


def normalize_trade(t: Mapping) -> dict:
    """trade : account, sizeDelta(Usd), price/executionPrice, isLong, timestamp."""
    return ligne(ts=_premier(t, "timestamp", "ts"), venue=VENUE,
                 symbole=_premier(t, "market", "indexToken", "symbol"), type_="trade",
                 prix=_premier(t, "executionPrice", "price"),
                 taille=_premier(t, "sizeDeltaUsd", "sizeDelta", "size"),
                 side=_side_from_islong(t), wallet=_premier(t, "account", "wallet"))


def registre_entites(mapping: Mapping[str, str]) -> dict:
    """DATA-093 : registre {compte -> entite}. resoudre() renvoie l'entite ou le compte lui-meme."""
    table = dict(mapping)

    def resoudre(compte):
        return table.get(compte, compte)

    return {"resoudre": resoudre, "n": len(table)}


def performance_par_compte(records: Sequence[Mapping]) -> dict:
    """DATA-092 : agrege realizedPnl par compte a partir de snapshots de performance. None ignore."""
    out: dict = {}
    for r in records:
        acc = _premier(r, "account", "wallet")
        pnl = to_float(_premier(r, "realizedPnl", "pnl", "cumulativePnl"))
        if acc and pnl is not None:
            out[acc] = out.get(acc, 0.0) + pnl
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def positions_par_compte(positions: Sequence[Mapping]) -> dict:
    """DATA-090 : indexe les positions ouvertes par compte."""
    out: dict = {}
    for p in positions:
        n = normalize_position(p)
        if n["wallet"]:
            out.setdefault(n["wallet"], []).append(n)
    return out


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("trades",), "adaptateur": OFFLINE_READY,
            "pull_live": REQUIRES_NETWORK, "note": "subgraph public ; pull = reseau"}


class LiveClientGMX(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def query_subgraph(self, entity):
        self._refuser("subgraph %s" % entity)
