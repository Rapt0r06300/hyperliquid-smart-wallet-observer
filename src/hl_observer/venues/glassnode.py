"""[DATA-101 / AUD-290,350] Adaptateur Glassnode (metriques on-chain point-in-time) — OFFLINE :
normalisation de series {t, v} + discipline POINT-IN-TIME (aucune donnee revisee du futur ; as-of
strict). Fournisseur PAYE : frontiere REQUIRES_KEY. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_KEY, to_float

VENUE = "glassnode"
ENDPOINTS = {"api": "https://api.glassnode.com/v1/metrics", "note": "cle API requise (payant)"}


def normalize_serie(points: Sequence[Mapping]) -> list:
    """Glassnode renvoie [{t, v}] (t = epoch s). -> [{ts, valeur}] trie par ts. v absent -> None."""
    out = [{"ts": p.get("t"), "valeur": to_float(p.get("v"))} for p in points or ()]
    return sorted(out, key=lambda x: (x["ts"] is None, x["ts"]))


def point_in_time(points: Sequence[Mapping], as_of: float) -> list:
    """AUD-350 / AUD-304 : ne garde QUE les points connus au plus tard a as_of (ts <= as_of). Interdit
    d'utiliser une valeur revisee/future : pas de lookahead."""
    a = to_float(as_of)
    s = normalize_serie(points)
    return [p for p in s if p["ts"] is not None and to_float(p["ts"]) is not None and to_float(p["ts"]) <= a]


def derniere_valeur_pit(points: Sequence[Mapping], as_of: float):
    """Derniere valeur CONNUE a as_of (point-in-time). None si rien de connu."""
    dispo = point_in_time(points, as_of)
    return dispo[-1]["valeur"] if dispo else None


def capacites() -> dict:
    return {"venue": VENUE, "flux": (), "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_KEY,
            "note": "fournisseur paye ; strictement point-in-time"}


class LiveClientGlassnode(ClientLiveBase):
    statut = REQUIRES_KEY
    exige_cle = True

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def get_metric(self, metric, asset):
        self._refuser("%s %s" % (metric, asset))
