"""[ALL lot2 #82] AGGREGATE MARKET-READY GATE : une stratégie reste INACTIVE tant que TOUTES les sources dont elle
dépend ne sont pas prêtes (carnet seedé, flux vivant, marks présents…). Démarrer avec une source manquante, c'est
décider sur un tableau incomplet. La porte n'ouvre que quand chaque source requise est prête. Source inconnue →
pas prête (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def pret(etats_sources: Mapping[str, Any]) -> dict[str, Any]:
    """Prêt seulement si CHAQUE source requise est explicitement prête (True/'READY'/'OK'). Toute source
    non-prête ou inconnue bloque. Aucune source déclarée → pas prêt (on ne démarre pas dans le vide)."""
    if not etats_sources:
        return {"pret": False, "raison": "AUCUNE_SOURCE_DECLAREE"}
    def _ok(v: Any) -> bool:
        return v is True or str(v).upper() in ("READY", "OK", "PRET", "UP")
    non_pretes = sorted(str(k) for k, v in etats_sources.items() if not _ok(v))
    ok = not non_pretes
    return {"pret": bool(ok), "sources_non_pretes": non_pretes,
            "raison": ("OK" if ok else "SOURCES_NON_PRETES")}


__all__ = ["pret"]
