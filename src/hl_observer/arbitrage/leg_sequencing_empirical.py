"""[ARB #45] LEG SEQUENCING EMPIRIQUE : si deux requêtes ne peuvent pas être atomiques, choisir l'ORDRE des jambes
selon les latences/échecs RÉELLEMENT observés de chaque venue. On exécute d'abord la jambe la plus INCERTAINE
(venue la moins fiable / la plus lente) : si elle échoue, on n'a pas encore engagé l'autre → aucun résidu. Poser
d'abord la jambe sûre exposerait à l'orphelinage si la seconde rate. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _risque(stat: Mapping[str, Any]) -> Any:
    """Score de risque d'une venue = proba d'échec, départagée par la latence. Stat incomplète → None."""
    if not isinstance(stat, Mapping):
        return None
    p, lat = stat.get("proba_echec"), stat.get("latence_ms")
    if not isinstance(p, (int, float)):
        return None
    return (float(p), float(lat) if isinstance(lat, (int, float)) else 0.0)


def ordonner_jambes(venue_a: str, stat_a: Mapping[str, Any], venue_b: str,
                    stat_b: Mapping[str, Any]) -> dict[str, Any]:
    """Renvoie l'ordre d'exécution : la venue la PLUS risquée d'abord. Stats manquantes → UNMEASURABLE
    (on ne devine pas un ordre sûr sans données observées)."""
    ra, rb = _risque(stat_a), _risque(stat_b)
    if ra is None or rb is None:
        return {"ordre": UNMEASURABLE, "raison": "STATS_VENUE_MANQUANTES"}
    # la plus risquée (proba d'échec puis latence les plus hautes) exécutée en premier
    if ra >= rb:
        premiere, seconde = venue_a, venue_b
    else:
        premiere, seconde = venue_b, venue_a
    return {"ordre": [premiere, seconde], "premiere": premiere, "seconde": seconde,
            "raison": "JAMBE_INCERTAINE_EN_PREMIER"}


__all__ = ["ordonner_jambes", "UNMEASURABLE"]
