"""[EXEC pépite 209] GHOST-ORDER DETECTOR : un ordre considéré LOCALEMENT actif mais ABSENT de la source autoritaire
est un « fantôme » — on croit avoir un ordre au travail qui, en réalité, n'existe plus (rejeté, expiré, annulé sans
qu'on l'ait vu). Continuer à raisonner comme s'il était vivant fausse l'exposition et le budget réservés. On détecte
ces fantômes pour les purger. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def detecter(locaux_actifs: Iterable[Any], source_actifs: Iterable[Any]) -> dict[str, Any]:
    """Fantômes = ordres actifs en local mais absents de la source autoritaire (à purger). Renvoie aussi s'il y en a."""
    loc = set(str(x) for x in locaux_actifs)
    src = set(str(x) for x in source_actifs)
    fantomes = sorted(loc - src)
    return {"fantomes": fantomes, "n": len(fantomes), "a_des_fantomes": bool(fantomes),
            "a_purger": fantomes}


__all__ = ["detecter"]
