"""ALPHA P60 — BOUCLE runtime → Factory : toute capture runtime alimente la DÉCOUVERTE. Forward frozen ISOLÉ.

Une nouvelle capture (fills, carnets) est automatiquement routée vers les recherches Discovery autorisées.
Le forward frozen reste STRICTEMENT séparé : une capture ne peut pas ré-alimenter/retuner un candidat déjà
scellé en forward. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def router_capture(captures: Sequence[Mapping[str, Any]], *, forward_frozen_ids: set[str]) -> dict[str, Any]:
    """Route les captures : vers DISCOVERY par défaut ; JAMAIS vers un candidat forward scellé (isolation)."""
    vers_discovery = []
    refuses_forward = []
    for c in captures:
        cible = c.get("cible_candidat")
        if cible is not None and str(cible) in forward_frozen_ids:
            refuses_forward.append(c)                    # isolation : on ne retouche pas le forward
        else:
            vers_discovery.append(c)
    return {"vers_discovery": vers_discovery, "n_discovery": len(vers_discovery),
            "refuses_forward_isolation": refuses_forward, "n_refuses": len(refuses_forward),
            "forward_isole": True}


__all__ = ["router_capture"]
