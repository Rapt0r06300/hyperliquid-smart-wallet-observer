"""G4 (article Punisher) — QUALITE des ticks WS : garde anti-stale + skip du 1er tick.

Deux couches du système « god-tier websockets », portées (on IGNORE la course de latence
100-300 sockets : la latence n'a jamais été notre problème) :
  * STALE-TICK GUARD : rejeter un tick dont le delta vs un prix de référence récent dépasse un
    seuil (delayed/corrompu). Empêche une donnée aberrante de polluer une décision.
  * FIRST-TICK SKIP : ignorer le tout premier tick après une (re)connexion (presque toujours un
    snapshot en cache, donc périmé).

Modules PURS / état minimal. On ne fabrique aucune donnée : un tick rejeté est ABSENT, pas corrigé.
PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DELTA_MAX_FRAC = 0.15         # un saut > 15% vs la référence récente = suspect (stale/corrompu)


def tick_est_stale(prix: float, prix_reference: float, *, delta_max_frac: float = DELTA_MAX_FRAC) -> bool:
    """True si le tick doit être REJETE (delta vs référence trop grand). Prix invalides -> stale."""
    try:
        p, r = float(prix), float(prix_reference)
    except (TypeError, ValueError):
        return True
    if p <= 0 or r <= 0:
        return True
    return abs(p - r) / r > float(delta_max_frac)


@dataclass(slots=True)
class GardeConnexion:
    """État par connexion : saute le 1er tick (snapshot en cache) après (re)connexion."""
    delta_max_frac: float = DELTA_MAX_FRAC
    _premier_vu: set = field(default_factory=set)

    def reconnexion(self, conn_id: str) -> None:
        """A appeler à chaque (re)connexion : le prochain tick de cette connexion sera SKIPPÉ."""
        self._premier_vu.discard(conn_id)

    def accepter(self, conn_id: str, prix: float, prix_reference: float | None) -> bool:
        """True si le tick est accepté. Skippe le 1er tick post-(re)connexion, puis applique le garde stale."""
        if conn_id not in self._premier_vu:
            self._premier_vu.add(conn_id)
            return False                                 # 1er tick = snapshot en cache -> SKIP
        if prix_reference is None:
            return True                                  # pas de référence -> on ne peut pas juger stale
        return not tick_est_stale(prix, prix_reference, delta_max_frac=self.delta_max_frac)


__all__ = ["DELTA_MAX_FRAC", "tick_est_stale", "GardeConnexion"]
