"""[DATA pépite 263] CANONICAL DATASET VERSION : tout changement de parser ou de schéma produit une NOUVELLE
version de dataset, jamais une modification silencieuse d'un ancien dataset. Sinon un backtest rejoué demain sur
« le même » dataset donne un résultat différent sans trace. La version canonique est un hash déterministe du
couple (parser_version, schema_version) ; une divergence impose un bump, jamais un écrasement. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

import hashlib
from typing import Any

INCHANGE = "INCHANGE"
NOUVELLE_VERSION = "NOUVELLE_VERSION"


def version_canonique(parser_version: Any, schema_version: Any) -> str:
    """Hash court, déterministe et stable du pipeline. Mêmes versions → même id ; toute différence → id différent."""
    empreinte = f"parser={parser_version}|schema={schema_version}"
    return hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:16]


def decider(pipeline_enregistre: dict[str, Any], parser_version: Any, schema_version: Any) -> dict[str, Any]:
    """Compare le pipeline déjà enregistré au pipeline courant. Identique → INCHANGE (réutilise la version).
    Différent → NOUVELLE_VERSION (on versionne, on n'écrase pas l'ancien dataset)."""
    v_courante = version_canonique(parser_version, schema_version)
    v_enregistree = version_canonique(pipeline_enregistre.get("parser_version"),
                                      pipeline_enregistre.get("schema_version"))
    if v_courante == v_enregistree:
        return {"action": INCHANGE, "version": v_courante}
    return {"action": NOUVELLE_VERSION, "version": v_courante, "ancienne_version": v_enregistree,
            "ecrasement_interdit": True}


__all__ = ["version_canonique", "decider", "INCHANGE", "NOUVELLE_VERSION"]
