"""[Bloc 55 / AUD-061,089,229,230] Anti-fuite IS/OOS/forward + gel des finalistes.

- verifier_pas_de_fuite : IS, OOS, forward doivent etre DISJOINTS et dans l'ordre temporel
  (max(IS) < min(OOS) < min(forward)). Toute intersection ou inversion = fuite.
- purge_embargo : retire du train les points a moins de `embargo` du test.
- geler_finalistes : fige l'ensemble des finalistes (hash) ; toute modif ulterieure est detectee
  (AUD-089 : forward inaccessible avant gel). deterministe."""
from __future__ import annotations

import hashlib
import json
from typing import Sequence


def verifier_pas_de_fuite(is_idx: Sequence[int], oos_idx: Sequence[int], forward_idx: Sequence[int]) -> dict:
    si, so, sf = set(is_idx), set(oos_idx), set(forward_idx)
    inter = (si & so) | (so & sf) | (si & sf)
    ordre_ok = True
    if si and so:
        ordre_ok = ordre_ok and max(si) < min(so)
    if so and sf:
        ordre_ok = ordre_ok and max(so) < min(sf)
    return {"fuite": bool(inter) or not ordre_ok, "intersection": sorted(inter), "ordre_ok": ordre_ok}


def purge_embargo(train: Sequence[int], test: Sequence[int], embargo: int) -> list:
    t = set(test)
    interdits = set()
    for x in test:
        for e in range(0, embargo + 1):
            interdits.add(x - e)
            interdits.add(x + e)
    return sorted(i for i in train if i not in t and i not in interdits)


def _hash_ensemble(finalists) -> str:
    return hashlib.sha256(json.dumps(sorted(finalists), sort_keys=True, default=str).encode()).hexdigest()


def geler_finalistes(finalists: Sequence) -> dict:
    """Fige les finalistes : frozenset + hash. Le forward ne doit plus toucher ces choix (AUD-089)."""
    gel = frozenset(finalists)
    return {"gel": gel, "hash": _hash_ensemble(gel), "n": len(gel)}


def gel_intact(gel_info: dict, finalists_maintenant: Sequence) -> bool:
    """Vrai si l'ensemble courant est IDENTIQUE au gel (aucune modif apres gel)."""
    return _hash_ensemble(frozenset(finalists_maintenant)) == gel_info["hash"]
