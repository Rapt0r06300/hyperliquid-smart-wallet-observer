"""[CROSS-VENUE #11] FEE SNAPSHOT PAR ÉPISODE : chaque opportunité FIGE les barèmes de frais qu'elle utilise,
au moment de son ouverture. Une modification ultérieure du barème (tier changé, promo terminée) ne doit JAMAIS
altérer rétroactivement le PnL d'un épisode déjà mesuré. Immuable + haché. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any


class SnapshotFrais:
    """Barème de frais SCELLÉ pour un épisode. Copie profonde à la construction : une mutation ultérieure de la
    source n'affecte pas le snapshot. `bareme` = {venue: {maker_bps, taker_bps, ...}}."""

    def __init__(self, episode_id: str, bareme: Mapping[str, Mapping[str, Any]]) -> None:
        self.episode_id = str(episode_id)
        self._fige: dict[str, dict[str, Any]] = copy.deepcopy({str(v): dict(b) for v, b in bareme.items()})
        self.hash = hashlib.sha1(
            json.dumps(self._fige, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    def frais_bps(self, venue: str, *, maker: bool = False) -> Any:
        """Frais figés (bps) de la venue au moment de l'épisode. None si la venue n'était pas dans le snapshot."""
        b = self._fige.get(str(venue))
        if not b:
            return None
        return b.get("maker_bps" if maker else "taker_bps")

    def bareme(self) -> dict[str, dict[str, Any]]:
        """Copie du barème figé (lecture seule : renvoie une copie pour que l'appelant ne puisse pas le muter)."""
        return copy.deepcopy(self._fige)

    def as_dict(self) -> dict[str, Any]:
        return {"episode_id": self.episode_id, "bareme_fige": self.bareme(), "hash": self.hash,
                "real_execution": False}


__all__ = ["SnapshotFrais"]
