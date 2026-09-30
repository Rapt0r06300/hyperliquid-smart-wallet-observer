"""[AUD-276] Registre HONNETE de disponibilite des venues. Chaque venue porte sa CAPACITE REELLE :
OFFLINE_READY (adaptateur + tests offline presents), REQUIRES_NETWORK (connecteur live NON prouvable
dans une sandbox paper/sans-reseau) ou NON_IMPLEMENTE. READY_MULTI_VENUE = aucune venue REQUISE n'est
NON_IMPLEMENTE. On ne declare JAMAIS une venue 'live-ok' sans preuve reseau -> pas de faux vert.
stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

OFFLINE_READY = "OFFLINE_READY"
REQUIRES_NETWORK = "REQUIRES_NETWORK"
NON_IMPLEMENTE = "NON_IMPLEMENTE"
_CAP = (OFFLINE_READY, REQUIRES_NETWORK, NON_IMPLEMENTE)


class RegistreVenues:
    """Etat HONNETE des venues : ce qui est prouvable hors-ligne vs ce qui exige un reseau live."""

    def __init__(self) -> None:
        self._v: dict[str, dict] = {}

    def declarer(self, venue: str, capacite: str, *, requis: bool = False) -> None:
        if capacite not in _CAP:
            raise ValueError("capacite invalide: %s" % capacite)
        self._v[venue] = {"venue": venue, "capacite": capacite, "requis": bool(requis)}

    def par_capacite(self, capacite: str) -> list[str]:
        return sorted(v for v, x in self._v.items() if x["capacite"] == capacite)

    def ready_multi_venue(self) -> dict:
        requises = [x for x in self._v.values() if x["requis"]]
        non_pretes = sorted(x["venue"] for x in requises if x["capacite"] == NON_IMPLEMENTE)
        return {"ready": len(non_pretes) == 0, "requises_non_pretes": non_pretes,
                "n_venues": len(self._v),
                "requiert_reseau": self.par_capacite(REQUIRES_NETWORK)}
