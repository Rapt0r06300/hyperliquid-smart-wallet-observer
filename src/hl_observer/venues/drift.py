"""[DATA-085..089 / AUD-281] Adaptateur Drift Protocol (perp Solana) — OFFLINE : normalisation de
records documentes (trades, funding payments, liquidations) vers le schema canonique + LOGIQUE
d'analyse copy-trading testable hors-ligne (decouverte de wallets, cycle de vie de position, funding
par wallet). Le pull LIVE (Data API on-chain) reste derriere REQUIRES_NETWORK. Normalizers DEFENSIFS
(plusieurs noms de champs plausibles) ; validation du schema live = golden packets (AUD-371).
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_NETWORK, ligne, norm_side, to_float

VENUE = "drift"
ENDPOINTS = {
    "data_api": "https://data.api.drift.trade",
    "records": ("trades", "fundingRates", "fundingPayments", "liquidations"),
}


def _premier(d: Mapping, *cles):
    for k in cles:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _wallet(d: Mapping) -> Optional[str]:
    return _premier(d, "authority", "wallet", "user", "userAuthority", "account")


def normalize_trade(t: Mapping) -> dict:
    """trade Drift : ts, market/symbol, price, baseAssetAmount/size, direction(long/short) ou taker side."""
    side = _premier(t, "direction", "side", "takerSide")
    return ligne(ts=_premier(t, "ts", "timestamp", "slot"), venue=VENUE,
                 symbole=_premier(t, "symbol", "marketSymbol", "marketIndex"), type_="trade",
                 prix=_premier(t, "price", "oraclePrice", "fillPrice"),
                 taille=_premier(t, "baseAssetAmount", "size", "baseAssetAmountFilled"),
                 side=side, wallet=_wallet(t))


def normalize_liquidation(l: Mapping) -> dict:
    return ligne(ts=_premier(l, "ts", "timestamp"), venue=VENUE,
                 symbole=_premier(l, "symbol", "marketIndex"), type_="liquidation",
                 prix=_premier(l, "price", "liquidationPrice"),
                 taille=_premier(l, "baseAssetAmount", "size"),
                 side=_premier(l, "direction", "side"), wallet=_wallet(l))


def wallets_actifs(trades: Sequence[Mapping]) -> dict:
    """DATA-086 : decouverte des wallets a partir de records de trades. count par wallet, trie."""
    compte: dict = {}
    for t in trades:
        w = _wallet(t)
        if w:
            compte[w] = compte.get(w, 0) + 1
    return dict(sorted(compte.items(), key=lambda kv: (-kv[1], kv[0])))


def cycles_position(events: Sequence[Mapping]) -> list:
    """DATA-087 : reconstruit le CYCLE DE VIE d'une position a partir d'events signes (size_delta) ordonnes.
    Un cycle s'ouvre quand le net quitte 0 et se ferme quand il y revient (ou sur liquidation). Aucune
    invention : si les events ne bouclent pas, le dernier cycle reste 'ouvert'."""
    cycles = []
    net = 0.0
    courant = None
    for e in events:
        d = to_float(_premier(e, "size_delta", "sizeDelta", "baseAssetAmount")) or 0.0
        typ = str(_premier(e, "type", "action") or "").lower()
        ts = _premier(e, "ts", "timestamp")
        if courant is None and d != 0.0:
            courant = {"ouverture_ts": ts, "cloture_ts": None, "raison": None}
        net += d
        if courant is not None and (abs(net) < 1e-12 or "liquidat" in typ):
            courant["cloture_ts"] = ts
            courant["raison"] = "liquidation" if "liquidat" in typ else "flat"
            cycles.append(courant)
            courant = None
            net = 0.0 if abs(net) < 1e-12 else net
    if courant is not None:
        courant["raison"] = "ouvert"
        cycles.append(courant)
    return cycles


def funding_par_wallet(paiements: Sequence[Mapping]) -> dict:
    """DATA-088 : somme des funding payments par wallet (amount signe). None ignore (jamais faux 0)."""
    out: dict = {}
    for p in paiements:
        w = _wallet(p)
        a = to_float(_premier(p, "amount", "fundingPayment", "quoteAssetAmount"))
        if w and a is not None:
            out[w] = out.get(w, 0.0) + a
    return out


def liquidations_par_wallet(records: Sequence[Mapping]) -> dict:
    """DATA-089 : nombre de liquidations par wallet (historique)."""
    out: dict = {}
    for r in records:
        w = _wallet(r)
        if w:
            out[w] = out.get(w, 0) + 1
    return out


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("trades", "funding", "liquidations"), "adaptateur": OFFLINE_READY,
            "pull_live": REQUIRES_NETWORK, "note": "donnees on-chain publiques ; pull = reseau"}


class LiveClientDrift(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def get_trades(self, market):
        self._refuser("trades %s" % market)

    def get_funding_payments(self, wallet):
        self._refuser("fundingPayments %s" % wallet)
