"""[ARB pépite 232] PRIMARY + SECONDARY HEDGE ROUTE : chaque opportunité possède, AVANT l'entrée, une route de hedge
PRINCIPALE ET une route paper de SECOURS distincte. Si la principale se dérobe (venue haltée, liquidité évaporée), on
a déjà un plan B validé au lieu de découvrir qu'on est coincé. Une opportunité sans route de secours n'est pas prête.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def preparer(*, route_principale: Any, route_secours: Any) -> dict[str, Any]:
    """Une opportunité est prête (côté routage) seulement si elle a une route principale ET une route de secours
    DISTINCTE. Secours manquant ou identique à la principale → non prête (pas de vrai plan B)."""
    if not route_principale:
        return {"pret": False, "raison": "ROUTE_PRINCIPALE_MANQUANTE"}
    if not route_secours:
        return {"pret": False, "raison": "ROUTE_SECOURS_MANQUANTE"}
    if str(route_secours) == str(route_principale):
        return {"pret": False, "raison": "SECOURS_IDENTIQUE_AU_PRINCIPAL"}
    return {"pret": True, "principale": route_principale, "secours": route_secours}


__all__ = ["preparer"]
