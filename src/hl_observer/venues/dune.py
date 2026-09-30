"""[DATA-097..098 / AUD-284,352] Adaptateur Dune Analytics (discovery queries, cached results) —
OFFLINE : registre de requetes + parsing de resultats caches + discipline de fraicheur. Fournisseur
PAYE et NON temps-reel : frontiere REQUIRES_KEY ; interdiction d'usage basse latence (AUD-352).
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ._canon import ClientLiveBase, OFFLINE_READY, REQUIRES_KEY, to_float

VENUE = "dune"
ENDPOINTS = {"api": "https://api.dune.com/api/v1", "note": "cle API requise ; resultats caches (batch)"}


def registre_requetes(defs: Sequence[Mapping]) -> dict:
    """DATA-097 : registre {query_id -> {name, params}} pour la discovery (jamais de query_id invente)."""
    out: dict = {}
    for d in defs:
        qid = d.get("query_id") or d.get("id")
        if qid is not None:
            out[str(qid)] = {"name": d.get("name"), "params": dict(d.get("params") or {})}
    return out


def normalize_resultat(payload: Mapping) -> dict:
    """DATA-098 : parse un result set Dune : result.rows + metadata (execution ts). n = nb lignes."""
    result = payload.get("result") or {}
    rows = list(result.get("rows") or ())
    meta = result.get("metadata") or payload.get("execution_ended_at") or {}
    as_of = payload.get("execution_ended_at") or (meta.get("execution_ended_at") if isinstance(meta, Mapping) else None)
    return {"venue": VENUE, "n": len(rows), "rows": rows, "as_of": as_of,
            "state": payload.get("state")}


def fraicheur(as_of: Optional[float], maintenant: float, ttl_s: float) -> dict:
    """AUD-351 : un cache paye expire. expire=True si (maintenant - as_of) > ttl. as_of absent -> inconnu."""
    a = to_float(as_of)
    if a is None:
        return {"expire": None, "age_s": None, "raison": "as_of_absent"}
    age = maintenant - a
    return {"expire": age > ttl_s, "age_s": age, "raison": None}


def usage_autorise(contexte: str) -> dict:
    """AUD-352 : Dune n'est PAS une source basse latence. Autorise en batch/recherche, refuse en
    execution/temps-reel."""
    bas_niveau = str(contexte).lower()
    interdit = bas_niveau in ("execution", "temps_reel", "realtime", "live", "hot_path")
    return {"autorise": not interdit, "contexte": bas_niveau}


def capacites() -> dict:
    return {"venue": VENUE, "flux": (), "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_KEY,
            "note": "batch only ; interdit basse latence (AUD-352)"}


class LiveClientDune(ClientLiveBase):
    statut = REQUIRES_KEY
    exige_cle = True

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def execute_query(self, query_id):
        self._refuser("execute %s" % query_id)

    def get_results(self, query_id):
        self._refuser("results %s" % query_id)
