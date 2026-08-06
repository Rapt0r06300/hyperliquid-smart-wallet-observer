"""[DATA-105..107 / AUD-291] Adaptateur DefiLlama (stablecoins, perps volume, DEX volume) — OFFLINE :
normalisation de records documentes + classification de REGIME (expansion/contraction) sur une serie.
API PUBLIQUE GRATUITE (aucune cle) : le pull LIVE exige seulement un reseau -> REQUIRES_NETWORK.
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_NETWORK, to_float

VENUE = "defillama"
ENDPOINTS = {
    "stablecoins": "https://stablecoins.llama.fi/stablecoins",
    "perps": "https://api.llama.fi/overview/derivatives",
    "dex": "https://api.llama.fi/overview/dexs",
    "note": "API publique gratuite ; reseau requis pour le pull",
}


def normalize_stablecoin(rec: Mapping) -> dict:
    """{name, symbol, circulating:{peggedUSD}} -> {actif, circulating_usd}."""
    circ = rec.get("circulating")
    if isinstance(circ, Mapping):
        circ = circ.get("peggedUSD")
    return {"venue": VENUE, "actif": rec.get("symbol") or rec.get("name"),
            "circulating_usd": to_float(circ)}


def normalize_perps_volume(rec: Mapping) -> dict:
    """DATA-106 : {name, total24h/dailyVolume} -> volume 24h."""
    return {"venue": VENUE, "protocole": rec.get("name"),
            "vol_24h": to_float(rec.get("total24h") or rec.get("dailyVolume"))}


def normalize_dex_volume(rec: Mapping) -> dict:
    """DATA-107 : volume DEX 24h."""
    return {"venue": VENUE, "protocole": rec.get("name"),
            "vol_24h": to_float(rec.get("total24h") or rec.get("dailyVolume"))}


def regime(serie: Sequence[float], k: int = 3, seuil: float = 0.05) -> dict:
    """AUD-291 : classe le REGIME a partir d'une serie (ex : circulating stablecoins ou volume perps).
    Compare la moyenne des k derniers points a celle des k precedents : > +seuil = expansion,
    < -seuil = contraction, sinon neutre. Serie trop courte -> regime None (jamais invente)."""
    xs = [to_float(v) for v in serie if to_float(v) is not None]
    if len(xs) < 2 * k:
        return {"regime": None, "raison": "serie_trop_courte"}
    recent = sum(xs[-k:]) / k
    avant = sum(xs[-2 * k:-k]) / k
    if avant == 0:
        return {"regime": None, "raison": "base_nulle"}
    var = (recent - avant) / abs(avant)
    reg = "expansion" if var > seuil else ("contraction" if var < -seuil else "neutre")
    return {"regime": reg, "variation": var}


def capacites() -> dict:
    return {"venue": VENUE, "flux": (), "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK,
            "note": "API publique gratuite ; reseau seulement (pas de cle)"}


class LiveClientDefiLlama(ClientLiveBase):
    statut = REQUIRES_NETWORK
    exige_cle = False

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def get_stablecoins(self):
        self._refuser("stablecoins")

    def get_perps_overview(self):
        self._refuser("derivatives overview")
