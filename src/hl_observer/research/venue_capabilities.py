"""[DATA-020 + disposition HONNETE des connecteurs 036-107] Registre des CAPACITES de venues : chaque
venue porte sa capacite REELLE — OFFLINE_READY (adaptateur + tests offline), REQUIRES_NETWORK
(connecteur live NON prouvable en sandbox paper/sans-reseau) ou NON_IMPLEMENTE — et sa MATRICE de flux
(book/trades/funding/oi/liquidations). READY_MULTI_VENUE = aucune venue REQUISE n'est NON_IMPLEMENTE.
On ne declare JAMAIS une venue 'live-ok' sans preuve reseau. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Sequence

OFFLINE_READY = "OFFLINE_READY"
REQUIRES_NETWORK = "REQUIRES_NETWORK"
NON_IMPLEMENTE = "NON_IMPLEMENTE"
_CAP = (OFFLINE_READY, REQUIRES_NETWORK, NON_IMPLEMENTE)
FLUX = ("book", "trades", "funding", "oi", "liquidations")


class RegistreCapacitesVenues:
    """Etat HONNETE des venues : ce qui est prouvable hors-ligne vs ce qui exige un reseau live."""

    def __init__(self) -> None:
        self._v: dict = {}

    def declarer(self, venue: str, capacite: str, *, flux: Sequence[str] = (), requis: bool = False) -> None:
        if capacite not in _CAP:
            raise ValueError("capacite invalide: %s" % capacite)
        self._v[venue] = {"venue": venue, "capacite": capacite,
                          "flux": {k: (k in set(flux)) for k in FLUX}, "requis": bool(requis)}

    def capacite(self, venue: str):
        v = self._v.get(venue)
        return v["capacite"] if v else None

    def par_capacite(self, capacite: str) -> list:
        return sorted(v for v, x in self._v.items() if x["capacite"] == capacite)

    def flux_supportes(self, venue: str) -> list:
        v = self._v.get(venue)
        return sorted(k for k, ok in v["flux"].items() if ok) if v else []

    def ready(self) -> dict:
        reqs = [x for x in self._v.values() if x["requis"]]
        non_pretes = sorted(x["venue"] for x in reqs if x["capacite"] == NON_IMPLEMENTE)
        return {"ready": len(non_pretes) == 0, "requises_non_pretes": non_pretes,
                "offline_ready": self.par_capacite(OFFLINE_READY),
                "requiert_reseau": self.par_capacite(REQUIRES_NETWORK)}


def registre_par_defaut() -> RegistreCapacitesVenues:
    """Etat HONNETE du projet : HL/dYdX/Binance ont des adaptateurs + tests offline ; les autres venues
    exigent un reseau live (non prouvable dans ce sandbox). Aucune n'est marquee 'live-ok'."""
    r = RegistreCapacitesVenues()
    tous = ("book", "trades", "funding", "oi", "liquidations")
    r.declarer("hyperliquid", OFFLINE_READY, flux=tous, requis=True)
    r.declarer("dydx", OFFLINE_READY, flux=tous)
    r.declarer("binance", OFFLINE_READY, flux=tous)
    for v in ("bybit", "okx", "coinbase", "deribit", "kraken", "drift", "gmx", "nansen", "dune", "glassnode", "defillama"):
        r.declarer(v, REQUIRES_NETWORK, flux=tous)
    return r
