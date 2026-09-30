"""[COPY-VAULT lot2 #52] METADATA-CHANGE REBOOTSTRAP : un changement de précision (tick/lot) ou de taille/notional
minimum INVALIDE les anciens paramètres de réplication — les tailles calculées avec l'ancienne précision ne sont
plus admissibles. On déclenche un rebootstrap des paramètres du coin. precision et limits sont distincts et
venue-specific (CCXT). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_CHAMPS = ("tick_size", "lot_size", "min_notional")


def doit_rebootstrap(meta_avant: Mapping[str, Any], meta_apres: Mapping[str, Any]) -> dict[str, Any]:
    """Rebootstrap si l'un des paramètres (tick/lot/min_notional) a changé. Metadata manquante → rebootstrap
    (prudence : on ne suppose pas que rien n'a bougé)."""
    if not isinstance(meta_avant, Mapping) or not isinstance(meta_apres, Mapping):
        return {"rebootstrap": True, "raison": "METADATA_MANQUANTE"}
    changes = []
    for k in _CHAMPS:
        av, ap = meta_avant.get(k), meta_apres.get(k)
        if av != ap:
            changes.append(k)
    if changes:
        return {"rebootstrap": True, "champs_changes": changes, "raison": "PARAMETRES_REPLICATION_INVALIDES"}
    return {"rebootstrap": False, "raison": "METADATA_INCHANGEE"}


__all__ = ["doit_rebootstrap"]
