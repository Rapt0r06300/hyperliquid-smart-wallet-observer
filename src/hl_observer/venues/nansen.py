"""[DATA-094..096 / AUD-283] Adaptateur Nansen (labels wallets, Smart Money, perp trades) — OFFLINE :
normalisation de records documentes + registre de labels. Fournisseur PAYE : le pull LIVE exige reseau
+ cle read-only -> frontiere REQUIRES_KEY (jamais de faux succes, jamais de label invente).
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_KEY, ligne

VENUE = "nansen"
ENDPOINTS = {"api": "https://api.nansen.ai", "note": "cle API read-only requise (payant)"}


def normalize_label(rec: Mapping) -> dict:
    """{address, labels:[...]} -> {venue, wallet, labels}. Aucun label invente (liste vide si absente)."""
    return {"venue": VENUE, "wallet": rec.get("address") or rec.get("wallet"),
            "labels": list(rec.get("labels") or ())}


def registre_labels(records: Sequence[Mapping]) -> dict:
    """Index address -> labels (DATA-094 / AUD-286 provenance des labels : source = Nansen)."""
    out: dict = {}
    for r in records:
        n = normalize_label(r)
        if n["wallet"]:
            out[n["wallet"]] = {"labels": n["labels"], "source": VENUE}
    return out


def smart_money(records: Sequence[Mapping]) -> list:
    """DATA-095 : liste des adresses marquees Smart Money (flag explicite ; jamais deduit)."""
    out = []
    for r in records:
        flag = r.get("smart_money", r.get("is_smart_money"))
        if flag in (True, "true", 1, "1") or (isinstance(flag, str) and flag.lower() == "smart_money"):
            out.append(r.get("address") or r.get("wallet"))
    return [a for a in out if a]


def normalize_perp_trade(t: Mapping) -> dict:
    """DATA-096 : perp trade Nansen -> canonique."""
    return ligne(ts=t.get("ts") or t.get("timestamp"), venue=VENUE,
                 symbole=t.get("pair") or t.get("symbol"), type_="trade",
                 prix=t.get("price"), taille=t.get("size"), side=t.get("side"),
                 wallet=t.get("address") or t.get("wallet"))


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("trades",), "adaptateur": OFFLINE_READY,
            "pull_live": REQUIRES_KEY, "note": "fournisseur paye : reseau + cle read-only"}


class LiveClientNansen(ClientLiveBase):
    statut = REQUIRES_KEY
    exige_cle = True

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def get_labels(self, address):
        self._refuser("labels %s" % address)

    def get_smart_money(self):
        self._refuser("smart_money")
