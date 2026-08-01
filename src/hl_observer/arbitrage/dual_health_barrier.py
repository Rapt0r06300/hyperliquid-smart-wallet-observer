"""[CROSS-VENUE #38] DUAL-HEALTH BARRIER : aucune NOUVELLE opportunité n'est ouverte si l'UNE des deux sources est
dégradée (données en retard, WS déconnecté, carnet trou), même si les prix affichés semblent fantastiques — un
prix fantastique sur une source malade est souvent un artefact de donnée périmée. Santé inconnue = dégradée
(fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

SAINE = "SAINE"
DEGRADEE = "DEGRADEE"


def _saine(etat: Any) -> bool:
    """True seulement si explicitement saine. Tout le reste (inconnu, None, dégradée) = pas saine."""
    if isinstance(etat, bool):
        return etat
    return str(etat).upper() in ("SAINE", "OK", "HEALTHY", "UP", "GREEN")


def peut_ouvrir(sante_a: Any, sante_b: Any) -> dict[str, Any]:
    """Ouverture autorisée seulement si les DEUX sources sont saines. Une seule dégradée/inconnue → refus."""
    a, b = _saine(sante_a), _saine(sante_b)
    ok = a and b
    degradees = [n for n, s in (("A", a), ("B", b)) if not s]
    return {"peut_ouvrir": bool(ok), "sources_degradees": degradees,
            "raison": ("OK" if ok else "SOURCE_DEGRADEE_FAIL_CLOSED")}


__all__ = ["peut_ouvrir", "SAINE", "DEGRADEE"]
