"""[DATA pépite 279] DEPENDENCY / API VERSION MANIFEST : chaque capture stocke les versions SDK / parser /
schema (et API venue) utilisées. Le jour où une donnée devient suspecte, ce manifest permet de savoir avec
quel code elle a été produite — et de rejouer exactement, ou d'invalider un lot lié à une version buggée. Un
manifest incomplet (version requise absente) est signalé, jamais rempli par défaut. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_REQUIS_DEFAUT = ("sdk_version", "parser_version", "schema_version")


def construire(versions: dict[str, Any], *, requis: tuple = _REQUIS_DEFAUT) -> dict[str, Any]:
    """Construit le manifest à partir des versions fournies. Toute clé requise absente ou vide → manifest
    incomplet (liste des manquants), pas de valeur par défaut inventée. Complet seulement si tout est présent."""
    if not isinstance(versions, dict):
        return {"complet": False, "manifest": {}, "manquants": list(requis), "raison": "VERSIONS_INVALIDE"}
    manquants = [k for k in requis if not versions.get(k)]
    manifest = {k: versions.get(k) for k in versions}
    return {"complet": len(manquants) == 0, "manifest": manifest, "manquants": manquants}


__all__ = ["construire"]
