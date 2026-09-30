"""[DATA pépite 264] RAW→CANONICAL REPRODUCIBILITY : reparser le raw AUJOURD'HUI doit produire le même hash
canonique pour la même version de pipeline. C'est la garantie qu'un dataset n'a pas dérivé en douce et qu'un
backtest est rejouable à l'identique. Le hash est calculé sur une projection canonique ordonnée + la version de
pipeline (deux pipelines différents → deux hash, à raison). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def hash_canonique(records: list[dict[str, Any]], pipeline_version: Any) -> str:
    """Hash déterministe : chaque record sérialisé avec clés triées, records dans l'ordre fourni (l'ordre fait
    partie du canonique), préfixé par la version de pipeline. Indépendant de l'itération de dict."""
    h = hashlib.sha256()
    h.update(f"pipeline={pipeline_version}\n".encode("utf-8"))
    for rec in records:
        h.update(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def verifier(hash_attendu: str, records: list[dict[str, Any]], pipeline_version: Any) -> dict[str, Any]:
    """Recompute le hash et compare. Divergence → non reproductible (le raw ou le pipeline a changé)."""
    recompute = hash_canonique(records, pipeline_version)
    reproductible = recompute == hash_attendu
    return {"reproductible": reproductible, "hash": recompute,
            "raison": None if reproductible else "HASH_DIFFERENT"}


__all__ = ["hash_canonique", "verifier"]
